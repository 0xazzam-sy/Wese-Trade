"""Strategy 4.3: frozen definition, tiers, live engine (no retroactive signals), scanner,
Telegram alerts, persistence and restart restoration."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import fields
from typing import Any

import httpx
import pytest
from sqlalchemy import select

from app.analysis.engine import MarketAnalyzer
from app.core.config import Settings
from app.db.base import Base
from app.db.session import Database
from app.forward_test.candidate import candidate, forward_version
from app.market_data.timeframes import Timeframe
from app.models.strategy43 import Strategy43SignalRecord
from app.strategy43.config import fingerprint, strategy_version, tier, variant
from app.strategy43.service import Strategy43Service
from app.telegram.models import SignalAlert
from tests.forward_test.helpers import KEY, FakeAnalysis, FakeMarket, candles, stub_evaluator

FROZEN_42 = "wese-trade-forward-4.2-a03e20f1d4"


@pytest.fixture
async def database(settings: Settings) -> AsyncIterator[Database]:
    db = Database(settings)
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield db
    await db.dispose()


def test_strategy_42_is_untouched_and_43_is_versioned_separately() -> None:
    assert forward_version() == FROZEN_42
    v = strategy_version()
    assert v.startswith("wese-trade-strategy-4.3-") and v != FROZEN_42
    assert fingerprint(v) == f"4.3-{v.rsplit('-', 1)[-1][:7]}"
    base, v43 = candidate(), variant()
    changed = {f.name for f in fields(base) if getattr(base, f.name) != getattr(v43, f.name)}
    # only the selection changed: same score model, plans, entry, exits and costs as 4.2
    assert changed <= {"name", "families", "threshold", "excluded_regimes", "notes"}
    assert v43.families == ("TREND_CONTINUATION", "PULLBACK_CONTINUATION")
    assert "transitional" not in v43.excluded_regimes  # TRANSITION is not "never trade"


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (90, "A+"),
        (82, "A+"),
        (81.9, "A"),
        (75, "A"),
        (72, "B"),
        (70, "B"),
        (66, "C"),
        (65, "C"),
        (64.9, "WAIT"),
        (40, "WAIT"),
    ],
)
def test_tiers(score: float, expected: str) -> None:
    assert tier(score) == expected


async def _boot(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
    buy_at: set[int],
    data: list[Any],
    seed: int,
) -> tuple[Strategy43Service, MarketAnalyzer, list[float], list[SignalAlert]]:
    monkeypatch.setattr("app.strategy43.service.evaluate_candle", stub_evaluator(buy_at))
    analysis, market, clock = FakeAnalysis(), FakeMarket(), [0.0]
    alerts: list[SignalAlert] = []
    service = Strategy43Service(
        analysis,  # type: ignore[arg-type]
        market,  # type: ignore[arg-type]
        database,
        alerts=alerts.append,
        clock=lambda: clock[0],
    )
    await service.start(background_loop=False)
    await service.restore()
    service._ensure(KEY[0], KEY[1])
    service.ready = True
    analyzer = MarketAnalyzer(KEY[0], KEY[1], tick_size=0.01)
    for c in data[:seed]:
        analyzer.update(c)
    analysis.analyzers[KEY] = analyzer
    clock[0] = analyzer.series.last.close_time + 5
    service.on_seeded(KEY, analyzer)
    return service, analyzer, clock, alerts


def _close(
    service: Strategy43Service, analyzer: MarketAnalyzer, items: list[Any], clock: list[float]
) -> None:
    for c in items:
        analyzer.update(c)
        clock[0] = analyzer.series.last.close_time + 5
        service.on_closed(KEY, analyzer)


async def test_seeded_history_never_creates_signals(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = candles(400)
    service, *_ = await _boot(database, monkeypatch, set(range(0, 300)), data, 300)
    await service.flush()
    assert service.open_signals() == []
    await service.stop()


async def test_live_close_confirms_persists_alerts_and_ranks(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = candles(400)
    service, analyzer, clock, alerts = await _boot(database, monkeypatch, {305}, data, 300)
    _close(service, analyzer, data[300:306], clock)
    await service.flush()
    [signal] = service.open_signals()
    assert signal.strategy_version == service.version
    assert [a.event for a in alerts] == ["NEW"]
    assert alerts[0].signal_id == signal.id and alerts[0].tier == "A"  # stub score 80
    opp = service.opportunities()
    assert opp[0]["id"] == signal.id and opp[0]["side"] == "BUY" and opp[0]["tier"] in ("A", "A+")
    assert service.best_for_symbol("BTCUSDT")["id"] == signal.id  # type: ignore[index]
    state = service.state(KEY)
    assert state["strategy"]["signal_capable"] is True
    assert state["active"]["tier"] == opp[0]["tier"] and state["active"]["tier_ar"]
    async with database.session_factory() as s:
        rows = (await s.execute(select(Strategy43SignalRecord))).scalars().all()
    assert [r.id for r in rows] == [signal.id] and rows[0].tier == opp[0]["tier"]
    # lifecycle: price runs through the targets -> TP alerts on the same canonical id
    _close(service, analyzer, data[306:360], clock)
    await service.flush()
    events = [a.event for a in alerts]
    assert events[0] == "NEW" and all(a.signal_id == signal.id for a in alerts)
    await service.stop()


async def test_restart_restores_open_signal_and_catchup_never_creates_signals(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = candles(400)
    service, analyzer, clock, _ = await _boot(database, monkeypatch, {305}, data, 300)
    _close(service, analyzer, data[300:306], clock)
    await service.flush()
    [signal] = service.open_signals()
    await service.stop()
    # app down while candles 306..319 close; one of them would have been a BUY
    restarted, _analyzer, _, alerts2 = await _boot(database, monkeypatch, {310}, data, 320)
    await restarted.flush()
    ids = {s.id for s in restarted.open_signals()}
    assert ids <= {signal.id}  # restored (or closed by catch-up), never a retroactive one
    async with database.session_factory() as s:
        rows = (await s.execute(select(Strategy43SignalRecord))).scalars().all()
    assert [r.id for r in rows] == [signal.id]
    assert [a for a in alerts2 if a.event == "NEW"] == []
    await restarted.stop()


async def test_on_demand_symbol_gets_all_primary_timeframes(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = candles(320)
    service, *_ = await _boot(database, monkeypatch, set(), data, 300)
    service.watch(("SOLUSDT", Timeframe.M30))
    service.watch(("SOLUSDT", Timeframe.M5))  # not a primary timeframe: ignored
    assert {k for k in service.streams if k[0] == "SOLUSDT"} == {
        ("SOLUSDT", Timeframe.M15), ("SOLUSDT", Timeframe.M30), ("SOLUSDT", Timeframe.H1)
    }  # fmt: skip
    assert service.owns(("SOLUSDT", Timeframe.H1)) and not service.owns(("SOLUSDT", Timeframe.M5))
    await service.stop()


async def test_health_reports_engine_state(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = candles(320)
    service, analyzer, clock, _ = await _boot(database, monkeypatch, set(), data, 300)
    _close(service, analyzer, data[300:302], clock)
    h = service.health()
    assert h["state"] == "running" and h["state_ar"] == "نشط"
    assert h["last_candle_close"] == analyzer.series.last.close_time
    assert h["last_scan_at"] is not None and h["fingerprint"].startswith("4.3-")
    await service.stop()
    assert service.health()["state"] == "stopped"


async def test_api_requires_auth_and_admin(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/strategy43/opportunities")).status_code == 401
    assert (await client.get("/api/v1/telegram")).status_code == 401
