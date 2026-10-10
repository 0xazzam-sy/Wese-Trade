"""Live execution service: parent link, live-close confirmation, persistence, restart."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import select

from app.analysis.engine import MarketAnalyzer
from app.analysis.models import AnalysisSnapshot
from app.analysis.series import Bar
from app.core.config import Settings
from app.db.base import Base
from app.db.session import Database
from app.execution.analyzer import ExecAnalyzer
from app.execution.models import Features, Level, Micro
from app.execution.service import ExecutionService
from app.market_data.timeframes import Timeframe
from app.models.execution import ExecutionSignalRecord
from app.signal_engine.enums import EntryModel, SetupFamily, Side, SignalClass
from app.signal_engine.models import Signal, Target, TradePlan
from tests.forward_test.helpers import FakeMarket, candles

VERSION = "wese-trade-forward-4.2-a03e20f1d4"
SYMBOL = "BTCUSDT"
K = 260  # the 1m candle that carries the execution trigger
EXEC = (SYMBOL, Timeframe.M1)


@pytest.fixture
async def database(settings: Settings) -> AsyncIterator[Database]:
    db = Database(settings)
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield db
    await db.dispose()


@dataclass
class Analysis:
    analyzers: dict[Any, MarketAnalyzer] = field(default_factory=dict)
    listeners: list[Any] = field(default_factory=list)
    viewers: set[str] = field(default_factory=lambda: {"browser-1"})

    def analyzer(self, key: Any) -> MarketAnalyzer | None:
        return self.analyzers.get(key)

    def consumers(self, key: Any) -> set[str]:
        return set(self.viewers)


class FakeMicro:
    def __init__(self, status: str = "ok") -> None:
        self.status = status
        self.refs: dict[str, int] = {}

    def acquire(self, symbol: str) -> None:
        self.refs[symbol] = self.refs.get(symbol, 0) + 1

    def release(self, symbol: str) -> None:
        self.refs[symbol] -= 1

    def snapshot(self, symbol: str) -> Micro:
        return Micro(status=self.status, spread_bp=1.0, spread_normal_bp=1.0)

    def health(self) -> dict[str, Any]:
        return {}

    async def close(self) -> None:
        return None


def parent_signal(close: float, tf: str = "15m", side: Side = Side.LONG) -> Signal:
    d = side.sign
    entry = close - 0.1 * d
    stop = close - 3.0 * d
    plan = TradePlan(
        entry_model=EntryModel.ZONE, entry_low=min(entry, close - 0.6 * d),
        entry_high=max(entry, close - 0.6 * d), preferred_entry=entry, stop=stop,
        invalidation=stop, stop_source="test", risk=abs(entry - stop), risk_atr=1.0,
        targets=(Target(close + 3.5 * d, 1.2, "t"), Target(close + 5 * d, 1.7, "t"),
                 Target(close + 7 * d, 2.4, "t")),
    )  # fmt: skip
    return Signal(
        id=f"fwd-{tf}-1", symbol=SYMBOL, timeframe=tf, side=side, signal_class=SignalClass.BUY,
        family=SetupFamily.TREND_CONTINUATION, score=80.0, trigger_id="t", trigger_time=0,
        confirmed_time=1, plan=plan, components=(), penalties=(), positive=(), negative=(),
        evidence={}, strategy_version=VERSION, regime=None,
    )  # fmt: skip


def forward(*signals: Signal) -> Any:
    return SimpleNamespace(
        name="Wese Trade Strategy 4.3",
        streams={
            (s.symbol, Timeframe(s.timeframe)): SimpleNamespace(tracker=SimpleNamespace(active=s))
            for s in signals
        },
    )


def favourable(self: ExecAnalyzer, bar: Bar, snap: AnalysisSnapshot, tick: float) -> Features:
    """Bullish execution evidence on every candle; the BOS trigger only on candle K."""
    c = bar.close
    return Features(
        index=bar.index, time=bar.time, close_time=bar.close_time, open=bar.open, high=bar.high,
        low=bar.low, close=c, prev_close=c + 0.2, atr=0.6, ema20=c - 0.1, ema50=c - 0.3,
        ema200=c - 1.0, ema20_prev=c - 0.15, ema_stack="bullish", regime="uptrend",
        direction="bullish", rsi=58.0, rsi_slope=3.0, structure_events=((K, "BOS", "bullish"),),
        sweeps=(), supports=(Level(c - 0.5, 8.0, "strong", "support"),), resistances=(),
        swing_low=None, swing_high=None, tick=tick,
    )  # fmt: skip


async def boot(
    database: Database | None,
    fwd: Any,
    seed: int,
    *,
    micro: Any = None,
    tf: Timeframe = Timeframe.M1,
) -> tuple[ExecutionService, MarketAnalyzer, Analysis, FakeMarket, list[float], list[Any]]:
    data = candles(400, tf)
    analysis, market, clock = Analysis(), FakeMarket(), [0.0]
    service = ExecutionService(
        analysis,  # type: ignore[arg-type]
        market,  # type: ignore[arg-type]
        database,
        fwd,
        micro,
        clock=lambda: clock[0],
    )
    await service.start(background_loop=False)
    analyzer = MarketAnalyzer(SYMBOL, tf, tick_size=0.1)
    for c in data[:seed]:
        analyzer.update(c)
    analysis.analyzers[(SYMBOL, tf)] = analyzer
    clock[0] = analyzer.series.last.close_time + 5
    service.on_seeded((SYMBOL, tf), analyzer)
    await settle(service)
    return service, analyzer, analysis, market, clock, data


async def settle(service: ExecutionService) -> None:
    for task in list(service._loading):
        await task
    await service.flush()


def drive(
    service: ExecutionService, analyzer: MarketAnalyzer, items: list[Any], clock: list[float]
) -> None:
    key = (SYMBOL, analyzer.timeframe)
    for c in items:
        analyzer.update(c)
        clock[0] = analyzer.series.last.close_time + 5
        service.on_closed(key, analyzer)


async def rows(database: Database) -> list[ExecutionSignalRecord]:
    async with database.session_factory() as session:
        return list((await session.execute(select(ExecutionSignalRecord))).scalars())


def last_state(market: FakeMarket) -> dict[str, Any]:
    events = [e for _, e in market.publisher.sent if e.type == "execution.update"]
    return dict(events[-1].data)


@pytest.fixture(autouse=True)
def _features(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ExecAnalyzer, "features", favourable)


def close_of(data: list[Any], i: int) -> float:
    return float(data[i].close)


async def test_15m_parent_confirms_1m_buy_on_live_close_and_persists(database: Database) -> None:
    data = candles(400, Timeframe.M1)
    fwd = forward(parent_signal(close_of(data, K)))
    service, analyzer, _, market, clock, data = await boot(database, fwd, K)
    assert last_state(market)["evaluation"]["decision"] == "WAIT"  # parent, no trigger yet
    drive(service, analyzer, data[K : K + 6], clock)
    await service.flush()
    stored = await rows(database)
    assert len(stored) == 1
    r = stored[0]
    assert (r.parent_strategy_version, r.parent_signal_id, r.parent_timeframe) == (
        VERSION, "fwd-15m-1", "15m",
    )  # fmt: skip
    assert r.parent_symbol == SYMBOL and r.timeframe == "1m" and r.side == 1
    assert r.candle_time == analyzer.series.bar(K).time  # marker on the confirmation candle
    state = last_state(market)
    assert state["evaluation"]["decision"] == "BUY"
    assert state["markers"] == [{"id": r.id, "time": r.candle_time, "side": 1, "state": r.state}]
    plan = state["signal"]["plan"]
    assert plan["targets"] == list(
        parent_signal(close_of(data, K)).plan.targets[i].price for i in range(3)
    )
    assert state["signal"]["parent"]["fingerprint"] == "4.2-a03e20f"
    await service.stop()


async def test_seeded_history_never_confirms(database: Database) -> None:
    data = candles(400, Timeframe.M1)
    service, *_ = await boot(database, forward(parent_signal(close_of(data, K))), K + 5)
    assert await rows(database) == []
    await service.stop()


async def test_no_parent_is_no_setup(database: Database) -> None:
    service, analyzer, _, market, clock, data = await boot(database, forward(), K)
    drive(service, analyzer, data[K : K + 2], clock)
    assert last_state(market)["evaluation"]["decision"] == "NO_SETUP"
    assert await rows(database) == []
    await service.stop()


async def test_1h_parent_is_not_a_1m_parent_but_30m_drives_10m(database: Database) -> None:
    data1 = candles(400, Timeframe.M1)
    service, analyzer, _, market, clock, data = await boot(
        database, forward(parent_signal(close_of(data1, K), tf="1h")), K
    )
    drive(service, analyzer, data[K : K + 1], clock)
    assert last_state(market)["evaluation"]["decision"] == "NO_SETUP"
    await service.stop()
    data10 = candles(400, Timeframe.M10)
    service, analyzer, _, market, clock, data = await boot(
        database, forward(parent_signal(close_of(data10, K), tf="30m")), K, tf=Timeframe.M10
    )
    drive(service, analyzer, data[K : K + 1], clock)
    ev = last_state(market)["evaluation"]
    assert ev["decision"] == "BUY" and ev["parent"]["timeframe"] == "30m"
    await service.stop()


async def test_stale_microstructure_blocks_confirmation(database: Database) -> None:
    data = candles(400, Timeframe.M1)
    service, analyzer, _, market, clock, data = await boot(
        database, forward(parent_signal(close_of(data, K))), K, micro=FakeMicro("stale")
    )
    drive(service, analyzer, data[K : K + 2], clock)
    await service.flush()
    assert await rows(database) == []
    assert last_state(market)["evaluation"]["decision"] == "WAIT"
    await service.stop()


async def test_restart_restores_signal_and_catches_up_without_duplicates(
    database: Database,
) -> None:
    data = candles(400, Timeframe.M1)
    fwd = forward(parent_signal(close_of(data, K)))
    service, analyzer, _, _, clock, data = await boot(database, fwd, K)
    drive(service, analyzer, data[K : K + 1], clock)
    await service.stop()
    first = await rows(database)
    assert len(first) == 1 and first[0].state == "ready"
    # restart later: candles K+1.. closed while the app was down -> lifecycle catch-up only
    service2, _, _, market, _, _ = await boot(database, fwd, K + 40)
    await service2.flush()
    after = await rows(database)
    assert len(after) == 1 and after[0].id == first[0].id
    assert after[0].state != "ready"  # advanced over the missed candles
    assert after[0].lifecycle["cursor"] > first[0].lifecycle["cursor"]
    assert last_state(market)["markers"][0]["id"] == first[0].id
    await service2.stop()


async def test_stream_and_micro_released_when_viewer_leaves(database: Database) -> None:
    micro = FakeMicro()
    data = candles(400, Timeframe.M1)
    service, _, analysis, _, _, _ = await boot(
        database, forward(parent_signal(close_of(data, K))), K, micro=micro
    )
    assert micro.refs[SYMBOL] == 1 and EXEC in service.streams
    analysis.viewers.clear()  # symbol / timeframe switched away
    service.tick()
    assert EXEC not in service.streams and micro.refs[SYMBOL] == 0
    await service.stop()
