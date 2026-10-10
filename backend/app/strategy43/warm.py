"""Warm-start opportunity restore (v1.2.1).

At startup (and when a chart opens a new symbol) the live engine used to treat all seeded
history as warm-up only, so no opportunity existed until the NEXT 15m / 30m / 1h candle
closed with a qualifying setup — often hours. This module replays the recent CLOSED
history through exactly the live pipeline:

    canonical MarketAnalyzer (+ context analyzers advanced to the same instant)
    -> `forward_test.evaluate.evaluate_candle` (the live evaluator, gates included)
    -> `SignalTracker` lifecycle (entry window, invalidation, stops, targets, expiry)

and returns the tracker as it stands after the last closed candle. Nothing is invented:
an opportunity exists only if Strategy 4.3 would have confirmed it on those closed
candles, and the tracker has already applied every later candle (entry missed /
invalidated / expired / stopped setups are closed). The caller decides what is still
ACTIONABLE now (`actionable()`), and never alerts Telegram for a restored signal.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from app.analysis.config import DEFAULT_CONFIG as ANALYSIS_CONFIG
from app.analysis.engine import MarketAnalyzer
from app.analysis.multi_timeframe.context import context_timeframes
from app.analysis.series import Bar
from app.forward_test.evaluate import LiveContext, evaluate_candle
from app.market_data.models import Candle
from app.market_data.timeframes import Timeframe
from app.research.simulate import Variant
from app.signal_engine.config import SignalConfig
from app.signal_engine.enums import SignalState
from app.signal_engine.lifecycle import SignalTracker
from app.signal_engine.models import Signal, SignalEvaluation

# Evaluate this many most recent closed candles (the analyzer is warmed on all of them).
# > max hold (96) + entry window + cooldown, so the final tracker state equals a replay
# of the full history (a trade opened earlier is closed by its time stop by then).
EVALUATE_LAST = 160
# An entered (ACTIVE) trade is still a usable opportunity only while price has not
# travelled more than this share of the way from entry to TP1.
ACTIVE_MAX_PROGRESS = 0.5


def bar_to_candle(bar: Bar, symbol: str, tf: Timeframe) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=tf,
        open_time=datetime.fromtimestamp(bar.time, tz=UTC),
        open=Decimal(repr(bar.open)),
        high=Decimal(repr(bar.high)),
        low=Decimal(repr(bar.low)),
        close=Decimal(repr(bar.close)),
        volume=Decimal(repr(bar.volume)),
        is_closed=True,
    )


@dataclass(slots=True)
class WarmResult:
    tracker: SignalTracker
    last_close: int  # close time (s) of the last replayed candle
    evaluations: int
    last_evaluation: SignalEvaluation | None


def replay(
    symbol: str,
    tf: Timeframe,
    tick: float,
    candles: Sequence[Candle],
    context: Mapping[Timeframe, Sequence[Candle]],
    *,
    variant: Variant,
    config: SignalConfig,
    version: str,
    evaluate_last: int = EVALUATE_LAST,
) -> WarmResult:
    """Pure: replay closed candles through the live evaluator + tracker (no I/O)."""
    analyzer = MarketAnalyzer(symbol, tf, tick_size=tick, config=ANALYSIS_CONFIG)
    ctx_tfs = context_timeframes(tf)
    ctx_an = {c: MarketAnalyzer(symbol, c, tick_size=tick, config=ANALYSIS_CONFIG) for c in ctx_tfs}
    ctx_pos = dict.fromkeys(ctx_tfs, 0)
    tracker = SignalTracker(symbol, tf.value, config, step_seconds=tf.seconds)
    first_eval = max(0, len(candles) - evaluate_last)
    evaluations = 0
    last_ev: SignalEvaluation | None = None
    last_close = 0
    for n, candle in enumerate(candles):
        close_ms = candle.open_ms + tf.milliseconds
        for c in ctx_tfs:
            series = context.get(c, ())
            i = ctx_pos[c]
            while i < len(series) and series[i].open_ms + c.milliseconds <= close_ms:
                ctx_an[c].update(series[i])
                i += 1
            ctx_pos[c] = i
        analyzer.update(candle)
        bar = analyzer.series.last
        last_close = bar.close_time
        tracker.on_bar(bar)  # lifecycle first, exactly like the live engine
        if n < first_eval:
            continue
        frames = [ctx_an[c].frame() for c in ctx_tfs]
        ev = evaluate_candle(
            variant,
            analyzer,
            frames,
            LiveContext(market_stale=False, symbol_active=True),
            strategy_version=version,
        )
        evaluations += 1
        last_ev = ev
        tracker.on_evaluation(ev, bar)
    return WarmResult(tracker, last_close, evaluations, last_ev)


def actionable(signal: Signal, price: float | None) -> bool:
    """Can the user still act on this opportunity now?

    * confirmed, waiting for the entry (the tracker already expired / invalidated it if
      the entry window passed or the setup broke) -> yes;
    * entered, no target hit, and price has not run more than half way to TP1 -> yes;
    * anything else (a target already hit, closed) -> no: the entry is no longer meaningful.
    """
    if signal.state is SignalState.CONFIRMED:
        return True
    if signal.state is not SignalState.ACTIVE or signal.targets_hit or price is None:
        return False
    d = signal.side.sign
    entry = signal.entry_price or signal.plan.preferred_entry
    tp1 = signal.plan.targets[0].price
    span = d * (tp1 - entry)
    if span <= 0:
        return False
    progress = d * (price - entry) / span
    beyond_stop = d * (price - signal.plan.stop) <= 0
    return progress <= ACTIVE_MAX_PROGRESS and not beyond_stop
