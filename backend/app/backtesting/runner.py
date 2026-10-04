"""Sequential historical replay with the canonical engines (no vectorized shortcuts).

For each execution candle N (ascending):
  1. every higher-timeframe analyzer consumes the context candles whose CLOSE time is
     <= close(N) (exactly what live trading knows at that moment);
  2. the execution MarketAnalyzer consumes candle N;
  3. SignalTracker.on_bar(N) advances the open signal with N's OHLC;
  4. if N confirmed a structure event: SignalEngine evaluates (runtime.evaluate_closed)
     and SignalTracker.on_evaluation(eval, N) may confirm a new signal.
At no point is a candle after N visible. Pass 1 (`replay`) records the evaluations so
pass 2 (`simulate`) can re-run ONLY the tracker for threshold/cooldown variants.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from app.analysis.config import DEFAULT_CONFIG as ANALYSIS_CONFIG
from app.analysis.config import AnalysisConfig
from app.analysis.engine import MarketAnalyzer
from app.analysis.multi_timeframe.context import context_timeframes
from app.analysis.series import Bar
from app.market_data.models import Candle
from app.market_data.timeframes import Timeframe
from app.signal_engine.config import SignalConfig
from app.signal_engine.engine import SignalEngine
from app.signal_engine.enums import Side, SignalClass
from app.signal_engine.lifecycle import SignalTracker
from app.signal_engine.models import Signal, SignalEvaluation
from app.signal_engine.runtime import evaluate_closed, has_trigger


@dataclass(slots=True)
class ReplayResult:
    symbol: str
    timeframe: str
    bars: list[Bar]
    evaluations: list[tuple[int, SignalEvaluation]]  # (bar index, evaluation with a plan)
    signals: list[Signal]
    suppressed: dict[str, int] = field(default_factory=dict)
    triggers: int = 0
    first_time: int = 0
    last_time: int = 0


def replay(
    symbol: str,
    timeframe: Timeframe,
    candles: Sequence[Candle],
    context: Mapping[Timeframe, Sequence[Candle]],
    *,
    tick: float,
    config: SignalConfig,
    analysis_config: AnalysisConfig = ANALYSIS_CONFIG,
) -> ReplayResult:
    engine = SignalEngine(config)
    analyzer = MarketAnalyzer(symbol, timeframe, tick_size=tick, config=analysis_config)
    ctx_tfs = context_timeframes(timeframe)
    ctx_an = {
        tf: MarketAnalyzer(symbol, tf, tick_size=tick, config=analysis_config) for tf in ctx_tfs
    }
    ctx_pos = dict.fromkeys(ctx_tfs, 0)
    tracker = SignalTracker(symbol, timeframe.value, config, step_seconds=timeframe.seconds)
    evaluations: list[tuple[int, SignalEvaluation]] = []
    triggers = 0
    for candle in candles:
        close_ms = candle.open_ms + timeframe.milliseconds
        for tf in ctx_tfs:
            series = context.get(tf, ())
            i = ctx_pos[tf]
            while i < len(series) and series[i].open_ms + tf.milliseconds <= close_ms:
                ctx_an[tf].update(series[i])
                i += 1
            ctx_pos[tf] = i
        analyzer.update(candle)
        bar = analyzer.series.last
        tracker.on_bar(bar)
        if not has_trigger(analyzer):
            continue
        triggers += 1
        frames = [ctx_an[tf].frame() for tf in ctx_tfs]
        ev = evaluate_closed(engine, analyzer, frames)
        if ev.plan is not None or ev.is_trade:
            evaluations.append((bar.index, ev))
        tracker.on_evaluation(ev, bar)
    bars = _all_bars(candles)
    if bars:
        tracker.finish_open(bars[-1].close_time, bars[-1].close)
    return ReplayResult(
        symbol,
        timeframe.value,
        bars,
        evaluations,
        tracker.closed,
        dict(tracker.suppressed),
        triggers,
        bars[0].time if bars else 0,
        bars[-1].close_time if bars else 0,
    )


def _all_bars(candles: Sequence[Candle]) -> list[Bar]:
    from app.analysis.series import to_bar

    return [to_bar(c, i) for i, c in enumerate(candles)]


def reclassify(ev: SignalEvaluation, config: SignalConfig) -> SignalEvaluation:
    """Apply (possibly different) thresholds to a recorded evaluation. Pure."""
    if ev.hypothesis is None:
        return ev
    regular, strong = config.threshold_for(ev.timeframe)
    top, other = max(ev.bull_score, ev.bear_score), min(ev.bull_score, ev.bear_score)
    hyp = ev.hypothesis
    cost_floor = config.min_risk_cost_multiple * config.round_trip_cost_rate()
    # Tolerance: pass 1 widens stops exactly to the floor computed from the UNROUNDED
    # preferred entry; `preferred_entry` is tick-rounded (a zone midpoint can move by half a
    # tick, ~3e-5 relative on SOL). Such plans must stay valid here.
    too_costly = ev.plan is not None and ev.plan.risk < cost_floor * ev.plan.preferred_entry * (
        1 - 1e-4
    )
    disabled = hyp.family.value not in config.enabled_families
    if (
        ev.plan is None
        or too_costly
        or disabled
        or top < regular
        or top - other < config.min_score_spread
    ):
        return replace(ev, signal_class=SignalClass.NEUTRAL, side=None)
    if config.strong_enabled and top >= strong:
        cls = SignalClass.STRONG_BUY if hyp.side is Side.LONG else SignalClass.STRONG_SELL
    else:
        cls = SignalClass.BUY if hyp.side is Side.LONG else SignalClass.SELL
    return replace(ev, signal_class=cls, side=hyp.side, neutral_reason=None)


def simulate(result: ReplayResult, config: SignalConfig) -> list[Signal]:
    """Pass 2: the same SignalTracker over recorded bars + reclassified evaluations."""
    step = Timeframe(result.timeframe).seconds
    tracker = SignalTracker(result.symbol, result.timeframe, config, step_seconds=step)
    by_index: dict[int, SignalEvaluation] = {
        index: reclassify(ev, config) for index, ev in result.evaluations
    }
    for bar in result.bars:
        tracker.on_bar(bar)
        found = by_index.get(bar.index)
        if found is not None:
            tracker.on_evaluation(found, bar)
    if result.bars:
        tracker.finish_open(result.bars[-1].close_time, result.bars[-1].close)
    return tracker.closed
