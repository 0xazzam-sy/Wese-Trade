"""v1.2.1: production == report config, research/live parity on real candles, warm-start
opportunity restore, parent discovery for 1m/5m/10m, live signal -> Telegram."""

from __future__ import annotations

import gzip
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.analysis.engine import MarketAnalyzer
from app.core.config import Settings
from app.db.base import Base
from app.db.session import Database
from app.execution.service import ExecutionService
from app.market_data.models import Candle
from app.market_data.timeframes import Timeframe
from app.models.strategy43 import Strategy43SignalRecord
from app.research import s43_report
from app.research.collect import collect
from app.research.simulate import evaluation
from app.signal_engine.enums import SignalState
from app.signal_engine.lifecycle import SignalTracker
from app.signal_engine.models import Signal
from app.strategy43 import config as s43config
from app.strategy43.config import TIER_FLOORS, TIMEFRAMES, fingerprint, strategy_version, variant
from app.strategy43.service import Strategy43Service
from app.strategy43.warm import actionable, replay
from app.telegram.models import SignalAlert
from app.telegram.service import TelegramService
from tests.forward_test.helpers import FakeAnalysis, FakeMarket, candles, stub_evaluator
from tests.telegram.test_telegram import TOKEN, FakeBot

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
PUBLISHED = "wese-trade-strategy-4.3-6044cea28a"
SYMBOL = "BTCUSDT"


@pytest.fixture
async def database(settings: Settings) -> AsyncIterator[Database]:
    db = Database(settings)
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield db
    await db.dispose()


# --- 16. report config == production config ---
def test_production_loads_exactly_the_published_report_config() -> None:
    assert strategy_version() == PUBLISHED
    assert fingerprint(PUBLISHED) == "4.3-6044cea"
    v = variant()
    assert v.families == ("TREND_CONTINUATION", "PULLBACK_CONTINUATION")
    assert v.threshold == 65.0 and v.spread == 10.0
    assert v.excluded_regimes == ("range",)
    assert (v.entry, v.runner, v.costs) == ("retrace", True, "base")
    assert TIER_FLOORS == (("A+", 82.0), ("A", 75.0), ("B", 70.0), ("C", 65.0))
    assert TIMEFRAMES == ("15m", "30m", "1h")
    # the report module evaluates the SAME variant object factory as production
    assert getattr(s43_report, "variant") is s43config.variant  # noqa: B009


# --- 15. research / live evaluator parity on real OKX candles ---
def _load(name: str) -> tuple[dict[Timeframe, list[Candle]], float]:
    raw = json.loads(gzip.decompress((FIXTURES / f"{name}.json.gz").read_bytes()))
    frames = {
        Timeframe(tf): [
            Candle(
                symbol=raw["symbol"],
                timeframe=Timeframe(tf),
                open_time=datetime.fromtimestamp(r[0] / 1000, tz=UTC),
                open=Decimal(r[1]),
                high=Decimal(r[2]),
                low=Decimal(r[3]),
                close=Decimal(r[4]),
                volume=Decimal(r[5]),
                is_closed=True,
            )
            for r in rows
        ]
        for tf, rows in raw["frames"].items()
    }
    return frames, float(raw["tick_size"])


def _summary(signals: list[Signal]) -> list[tuple[str, str, float, int, str, int]]:
    return [
        (s.id, s.side.value, round(s.score, 6), s.confirmed_time, s.state.value, s.targets_hit)
        for s in signals
    ]


def test_research_report_and_live_evaluator_produce_the_same_signals() -> None:
    frames, tick = _load("frozen_buy")
    base = frames[Timeframe.M15]
    ctx = {tf: frames[tf] for tf in (Timeframe.M30, Timeframe.H1)}
    v = variant()
    cfg = v.tracker_config()
    # research / report path: pass-1 collect + the shared selection rule
    series = collect("ETHUSDT", Timeframe.M15, base, ctx, tick=tick)
    research = SignalTracker("ETHUSDT", "15m", cfg, step_seconds=900)
    by_index = {t.index: t for t in series.triggers}
    for bar in series.bars:
        research.on_bar(bar)
        trig = by_index.get(bar.index)
        if trig is not None and (ev := evaluation(v, series, trig)) is not None:
            research.on_evaluation(ev, bar)
    # production path: the live evaluator used by the engine and the warm start
    live = replay(
        "ETHUSDT", Timeframe.M15, tick, base, ctx, variant=v, config=cfg,
        version=PUBLISHED, evaluate_last=len(base),
    ).tracker  # fmt: skip
    rs = [*research.closed, *([research.active] if research.active else [])]
    ls = [*live.closed, *([live.active] if live.active else [])]
    assert len(rs) >= 1, "fixture must contain at least one Strategy 4.3 signal"
    assert _summary(ls) == _summary(rs)
    assert [s.plan for s in ls] == [s.plan for s in rs]
    # the bounded warm-start window ends in the same state as the full replay
    bounded = replay("ETHUSDT", Timeframe.M15, tick, base, ctx, variant=v, config=cfg,
                     version=PUBLISHED).tracker  # fmt: skip
    assert (bounded.active.id if bounded.active else None) == (
        live.active.id if live.active else None
    )


# --- actionable rules ---
def _signal(state: SignalState, *, price_entry: float = 100.0, hits: int = 0) -> Any:
    plan = SimpleNamespace(
        preferred_entry=100.0, stop=98.0, targets=(SimpleNamespace(price=104.0),) * 3
    )
    return SimpleNamespace(
        state=state, targets_hit=hits, side=SimpleNamespace(sign=1), entry_price=price_entry,
        plan=plan,
    )  # fmt: skip


def test_actionable_rules() -> None:
    assert actionable(_signal(SignalState.CONFIRMED), None)  # waiting for entry
    assert actionable(_signal(SignalState.ACTIVE), 101.0)  # entered, 25% to TP1
    assert not actionable(_signal(SignalState.ACTIVE), 103.0)  # 75% to TP1: entry missed
    assert not actionable(_signal(SignalState.ACTIVE), 97.5)  # beyond the stop
    assert not actionable(_signal(SignalState.TP1_HIT, hits=1), 101.0)  # TP1 done
    for final in (SignalState.EXPIRED, SignalState.INVALIDATED, SignalState.STOPPED):
        assert not actionable(_signal(final), 100.0)


# --- warm-start service ---
def _analyzers(n15: int = 400) -> dict[Any, MarketAnalyzer]:
    out = {}
    for tf, n in ((Timeframe.M15, n15), (Timeframe.M30, 150), (Timeframe.H1, 90)):
        a = MarketAnalyzer(SYMBOL, tf, tick_size=0.01)
        for c in candles(n, tf):
            a.update(c)
        out[(SYMBOL, tf)] = a
    return out


async def _service(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
    buy_at: set[int],
    *,
    alerts: list[SignalAlert] | None = None,
    zone_offset: float | None = 5.0,
) -> tuple[Strategy43Service, FakeAnalysis, list[float]]:
    monkeypatch.setattr(
        "app.strategy43.warm.evaluate_candle", stub_evaluator(buy_at, zone_offset=zone_offset)
    )
    analysis, market, clock = FakeAnalysis(), FakeMarket(), [0.0]
    analysis.analyzers.update(_analyzers())
    sink = alerts.append if alerts is not None else None
    service = Strategy43Service(
        analysis,  # type: ignore[arg-type]
        market,  # type: ignore[arg-type]
        database,
        alerts=sink,
        clock=lambda: clock[0],
    )
    await service.start(background_loop=False)
    await service.restore()
    for tf in TIMEFRAMES:
        service._ensure(SYMBOL, Timeframe(tf))
    service.ready = True
    last15 = analysis.analyzers[(SYMBOL, Timeframe.M15)].series.last
    clock[0] = last15.close_time + 30  # market data is fresh
    return service, analysis, clock


async def test_warm_start_restores_an_actionable_opportunity_without_telegram(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    alerts: list[SignalAlert] = []
    service, *_ = await _service(database, monkeypatch, {398}, alerts=alerts)
    assert service.opportunities() == []  # before: the v1.2.0 symptom
    assert await service.warm_start(SYMBOL, wait_seconds=1) == 1
    await service.flush()
    [opp] = service.opportunities()  # scanner populated immediately
    assert opp["symbol"] == SYMBOL and opp["timeframe"] == "15m" and opp["side"] == "BUY"
    assert opp["state"] == "confirmed" and opp["tier"] == "A"
    assert service.best_for_symbol(SYMBOL)["id"] == opp["id"]  # type: ignore[index]
    assert alerts == []  # restored from history: never pushed as a new alert
    async with database.session_factory() as s:
        rows = (await s.execute(select(Strategy43SignalRecord))).scalars().all()
    assert [r.id for r in rows] == [opp["id"]]
    assert rows[0].lifecycle["evidence"]["warm_start"] is True
    h = service.health()
    assert h["warm_restored"] == 1 and h["open_opportunities"] == 1
    assert h["open_by_tier"]["A"] == 1
    await service.stop()


async def test_expired_setup_is_not_restored(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, *_ = await _service(database, monkeypatch, {370})  # entry window long gone
    assert await service.warm_start(SYMBOL, wait_seconds=1) == 0
    assert service.opportunities() == []
    tracker = service.streams[(SYMBOL, Timeframe.M15)].tracker
    assert tracker.active is None
    assert [s.state for s in tracker.closed] == [SignalState.EXPIRED]
    await service.stop()


async def test_stale_market_data_is_not_restored(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, _analysis, clock = await _service(database, monkeypatch, {398})
    clock[0] += 3 * 3600  # last closed candle is hours old
    assert await service.warm_start(SYMBOL, wait_seconds=1) == 0
    assert service.opportunities() == []
    await service.stop()


async def test_parent_is_found_by_execution_charts_and_survives_restart(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, analysis, _clock = await _service(database, monkeypatch, {398})
    await service.warm_start(SYMBOL, wait_seconds=1)
    await service.flush()
    [opp] = service.opportunities()
    market = FakeMarket()
    execution = ExecutionService(analysis, market, database, service)  # type: ignore[arg-type]
    for tf in ("1m", "5m"):  # 15m parent -> 1m and 5m
        parent, conflict = __import__(
            "app.execution.engine", fromlist=["select_parent"]
        ).select_parent(tf, execution.parents(SYMBOL))
        assert parent is not None and parent.signal_id == opp["id"] and not conflict
    assert execution.state((SYMBOL, Timeframe.M1))["best"]["id"] == opp["id"]
    await service.stop()
    # restart: the parent is restored from the database (no warm replay needed)
    restarted, analysis2, _ = await _service(database, monkeypatch, set())
    assert restarted.streams[(SYMBOL, Timeframe.M15)].tracker.active.id == opp["id"]  # type: ignore[union-attr]
    assert await restarted.warm_start(SYMBOL, wait_seconds=1) == 0  # skipped: live state kept
    execution2 = ExecutionService(analysis2, FakeMarket(), database, restarted)  # type: ignore[arg-type]
    assert [p.signal_id for p in execution2.parents(SYMBOL)] == [opp["id"]]
    await restarted.stop()


async def test_selected_symbol_is_scanned_immediately(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    service, analysis, _ = await _service(database, monkeypatch, {398})
    other = "MAGICUSDT"
    for (_sym, tf), a in _analyzers().items():
        b = MarketAnalyzer(other, tf, tick_size=0.01)
        for bar in a.series.tail(len(a.series)):
            from app.strategy43.warm import bar_to_candle

            b.update(bar_to_candle(bar, other, tf))
        analysis.analyzers[(other, tf)] = b
    service.watch_symbol(other)  # e.g. a 5m chart of a symbol outside the scanner universe
    assert {k for k in service.streams if k[0] == other} == {
        (other, Timeframe(tf)) for tf in TIMEFRAMES
    }
    assert await service.warm_start(other, wait_seconds=1) == 1
    assert service.best_for_symbol(other) is not None
    await service.stop()


# --- 8. live signal -> Telegram, no duplicate after restart ---
async def test_live_signal_reaches_telegram_once_even_after_restart(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_sleep(_: float) -> None:
        return None

    FakeBot.sent = []
    FakeBot.fail = []
    tg = TelegramService(database, "k" * 48, client_factory=FakeBot, sleep=no_sleep)  # type: ignore[arg-type]
    await tg.start()
    await tg.set_token(TOKEN)
    await tg.add_recipient({"name": "Azzam", "chat_id": "5002606147"})
    monkeypatch.setattr("app.strategy43.service.evaluate_candle", stub_evaluator({401}))
    service, analysis, clock = await _service(database, monkeypatch, set())
    service.alerts = tg.notify
    key = (SYMBOL, Timeframe.M15)
    analyzer = analysis.analyzers[key]
    service.on_seeded(key, analyzer)
    for c in candles(403)[400:402]:  # two live closes; BUY confirmed on bar 401
        analyzer.update(c)
        clock[0] = analyzer.series.last.close_time + 5
        service.on_closed(key, analyzer)
    await service.flush()
    await tg.drain()
    [signal] = service.open_signals()
    assert len(FakeBot.sent) == 1 and "BUY — شراء" in FakeBot.sent[0][1]
    async with database.session_factory() as s:
        row = await s.get(Strategy43SignalRecord, signal.id)
    assert row is not None  # the SAME id persisted, published and delivered
    await tg.stop()
    await service.stop()
    tg2 = TelegramService(database, "k" * 48, client_factory=FakeBot, sleep=no_sleep)  # type: ignore[arg-type]
    await tg2.start()
    tg2.notify(replace(service.alert_for(signal, "NEW")))
    await tg2.drain()
    assert len(FakeBot.sent) == 1  # never resent after restart
    await tg2.stop()
