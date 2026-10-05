"""Fakes and deterministic fixtures for forward-test tests (no network)."""

from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.analysis.engine import MarketAnalyzer
from app.analysis.series import Bar
from app.forward_test.service import ForwardTestService
from app.market_data.models import Candle
from app.market_data.timeframes import Timeframe
from app.signal_engine.enums import EntryModel, SetupFamily, Side, SignalClass
from app.signal_engine.models import SignalEvaluation, Target, TradePlan
from tests.research.test_research import _hyp

KEY = ("BTCUSDT", Timeframe.M15)
T0 = 1_790_000_100 // 900 * 900  # aligned 15m open time


def candles(n: int, tf: Timeframe = Timeframe.M15, symbol: str = "BTCUSDT") -> list[Candle]:
    out = []
    for i in range(n):
        mid = 100 + 3 * math.sin(i / 7) + i * 0.01
        out.append(
            Candle(
                symbol=symbol,
                timeframe=tf,
                open_time=datetime.fromtimestamp(T0 + i * tf.seconds, tz=UTC),
                open=Decimal(str(round(mid, 2))),
                high=Decimal(str(round(mid + 1.2, 2))),
                low=Decimal(str(round(mid - 1.2, 2))),
                close=Decimal(str(round(mid + 0.3, 2))),
                volume=Decimal("10"),
                is_closed=True,
            )
        )
    return out


def open_time(i: int, tf: Timeframe = Timeframe.M15) -> int:
    return T0 + i * tf.seconds


class FakePublisher:
    def __init__(self) -> None:
        self.sent: list[tuple[set[str], Any]] = []

    def send_to(self, consumers: Any, envelope: Any) -> None:
        self.sent.append((set(consumers), envelope))


@dataclass
class FakeMarket:
    publisher: FakePublisher = field(default_factory=FakePublisher)
    state: str = "live"
    inactive: set[str] = field(default_factory=set)
    subscriptions: list[tuple[str, str, Timeframe]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.health = SimpleNamespace(overall="connected")
        market = self

        class _Symbols:
            loaded = True

            def get(self, symbol: str) -> Any:
                return SimpleNamespace(is_active=symbol not in market.inactive)

        self.symbols = _Symbols()

    def stream_state(self, key: Any) -> str:
        return self.state

    async def subscribe(self, consumer: str, symbol: str, tf: Timeframe) -> None:
        self.subscriptions.append((consumer, symbol, tf))

    async def unsubscribe(self, consumer: str, symbol: str, tf: Timeframe) -> None:
        return None


@dataclass
class FakeAnalysis:
    analyzers: dict[Any, MarketAnalyzer] = field(default_factory=dict)
    listeners: list[Any] = field(default_factory=list)
    viewers: set[str] = field(default_factory=lambda: {"browser-1"})

    def analyzer(self, key: Any) -> MarketAnalyzer | None:
        return self.analyzers.get(key)

    def context_frames(self, key: Any) -> list[Any]:
        return []

    def consumers(self, key: Any) -> set[str]:
        return {"forward-test", *self.viewers}

    async def subscribe(self, consumer: str, symbol: str, tf: Timeframe) -> None:
        return None

    async def unsubscribe(self, consumer: str, symbol: str, tf: Timeframe) -> None:
        return None


def stub_evaluator(buy_at: set[int], *, zone_offset: float | None = None) -> Any:
    """Deterministic evaluation: BUY on the given bar indices, NEUTRAL otherwise."""

    def evaluate(
        v: Any, analyzer: MarketAnalyzer, frames: Any, ctx: Any, *, strategy_version: str, **_: Any
    ) -> SignalEvaluation:
        bar: Bar = analyzer.series.last
        base = SignalEvaluation(
            "BTCUSDT",
            "15m",
            bar.time,
            False,
            SignalClass.NEUTRAL,
            None,
            0.0,
            0.0,
            0.0,
            None,
            None,
            None,
            None,
            "neutral",
            strategy_version,
        )
        if bar.index not in buy_at or ctx.market_stale or not ctx.symbol_active:
            return base
        hyp = _hyp({"htf": 1.0}, {})
        hyp = replace(
            hyp,
            family=SetupFamily.TREND_CONTINUATION,
            trigger=replace(hyp.trigger, id=f"t{bar.index}"),
            score=80.0,
        )
        entry = bar.close if zone_offset is None else bar.close - zone_offset
        stop = entry - 2.0
        plan = TradePlan(
            entry_model=EntryModel.MARKET if zone_offset is None else EntryModel.ZONE,
            entry_low=entry,
            entry_high=bar.close,
            preferred_entry=entry,
            stop=stop,
            invalidation=stop,
            stop_source="test",
            risk=2.0,
            risk_atr=1.0,
            targets=(
                Target(entry + 2, 1.0, "t"),
                Target(entry + 4, 2.0, "t"),
                Target(entry + 6, 3.0, "t"),
            ),
        )
        return replace(
            base,
            signal_class=SignalClass.BUY,
            side=Side.LONG,
            score=80.0,
            hypothesis=hyp,
            plan=plan,
            neutral_reason=None,
        )

    return evaluate


def make_service(
    database: Any, analysis: FakeAnalysis, market: FakeMarket, clock: list[float]
) -> ForwardTestService:
    return ForwardTestService(analysis, market, database, clock=lambda: clock[0])  # type: ignore[arg-type]


def drive(
    service: ForwardTestService, analyzer: MarketAnalyzer, items: list[Candle], clock: list[float]
) -> None:
    """Live closes: update the analyzer, then notify the service (like AnalysisService)."""
    for c in items:
        analyzer.update(c)
        clock[0] = analyzer.series.last.close_time + 5
        service.on_closed(KEY, analyzer)
