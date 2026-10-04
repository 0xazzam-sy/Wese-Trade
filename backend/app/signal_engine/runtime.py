"""Glue shared VERBATIM by live Wese Trade and historical replay (one code path).

A confirmed evaluation happens at a candle close, from the analyzer state after that
candle, with higher-timeframe frames whose candles CLOSED at or before that moment, and
WITHOUT the forming candle. Only candles that confirmed a structure event can trigger a
setup, so other candles are NEUTRAL by definition and are skipped (pure optimization:
`SignalEngine.evaluate` would return NEUTRAL "no trigger" for them).
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.analysis.engine import MarketAnalyzer
from app.analysis.models import MtfFrame
from app.market_data.models import Candle
from app.signal_engine.engine import SignalEngine
from app.signal_engine.models import SignalEvaluation, SignalInput

RECENT_BARS = 30
FIXED_TIME = datetime(2000, 1, 1, tzinfo=UTC)  # snapshots used for signals carry no wall time


def has_trigger(analyzer: MarketAnalyzer) -> bool:
    last = len(analyzer.series) - 1
    return any(t.events and t.events[-1].index == last for t in (analyzer.swing, analyzer.internal))


def evaluate_closed(
    engine: SignalEngine,
    analyzer: MarketAnalyzer,
    context: list[MtfFrame],
    *,
    market_stale: bool = False,
    symbol_active: bool = True,
) -> SignalEvaluation:
    snapshot = analyzer.snapshot(None, context=context, generated_at=FIXED_TIME)
    return engine.evaluate(
        SignalInput(
            snapshot=snapshot,
            recent_bars=tuple(analyzer.series.tail(RECENT_BARS)),
            tick_size=analyzer.tick,
            market_stale=market_stale,
            symbol_active=symbol_active,
        )
    )


def evaluate_developing(
    engine: SignalEngine,
    analyzer: MarketAnalyzer,
    forming: Candle,
    context: list[MtfFrame],
    *,
    market_stale: bool = False,
) -> SignalEvaluation:
    snapshot = analyzer.snapshot(forming, context=context, generated_at=FIXED_TIME)
    return engine.evaluate(
        SignalInput(
            snapshot=snapshot,
            recent_bars=tuple(analyzer.series.tail(RECENT_BARS)),
            tick_size=analyzer.tick,
            developing=True,
            market_stale=market_stale,
        )
    )
