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
from app.execution.engine import MISSED_PROGRESS_R, MISSED_RR_TP1
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
# Actionability uses the execution layer's own entry rules (1m / 5m / 10m) so the scanner
# never lists what the execution charts would call ENTRY MISSED or invalid.


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

    Same location rule as the execution layer (`execution.engine._location`): the setup
    is open (confirmed or entered, no target hit), price has not reached the invalidation /
    stop, has not run more than MISSED_PROGRESS_R beyond the planned entry, and the
    remaining R:R to TP1 is at least MISSED_RR_TP1. Closed, expired, invalidated or
    TP-hit setups are never actionable.
    """
    if signal.state not in (SignalState.CONFIRMED, SignalState.ACTIVE) or signal.targets_hit:
        return False
    if price is None:
        return signal.state is SignalState.CONFIRMED
    plan = signal.plan
    d = signal.side.sign
    risk = d * (plan.preferred_entry - plan.stop)
    room = d * (price - plan.stop)
    if risk <= 0 or room <= 0 or d * (price - plan.invalidation) <= 0:
        return False
    progress = d * (price - plan.preferred_entry) / risk
    rr1 = d * (plan.targets[0].price - price) / room
    return progress <= MISSED_PROGRESS_R and rr1 >= MISSED_RR_TP1
