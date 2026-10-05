"""Live evaluation of the frozen candidate on one CLOSED candle.

Exactly the research pipeline, on live analyzer state:
  canonical MarketAnalyzer snapshot (+ context frames closed at the same instant)
  -> canonical SignalEngine gate (not ready / stale / inactive / volatility / no HTF)
  -> canonical scoring + plans for every hypothesis (`research.collect.research_hypotheses`)
  -> the shared variant selection rule (`research.simulate.evaluate_hyps`).
There is no separate forward-test strategy implementation.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from app.analysis.engine import MarketAnalyzer
from app.analysis.models import MtfFrame
from app.research.collect import ALL_FAMILIES, research_hypotheses
from app.research.simulate import REASON_GATED, Variant, evaluate_hyps
from app.signal_engine.config import DEFAULT_SIGNAL_CONFIG, SignalConfig
from app.signal_engine.engine import NEUTRAL_TEXT, SignalEngine
from app.signal_engine.enums import SignalClass
from app.signal_engine.models import SignalEvaluation, SignalInput
from app.signal_engine.runtime import FIXED_TIME, RECENT_BARS, has_trigger

_ENGINES: dict[int, tuple[SignalEngine, SignalEngine]] = {}


def _engines(config: SignalConfig) -> tuple[SignalEngine, SignalEngine]:
    """(gate engine, all-family scoring engine) exactly as research pass 1 builds them."""
    key = id(config)
    if key not in _ENGINES:
        _ENGINES[key] = (
            SignalEngine(config),
            SignalEngine(config.with_changes(enabled_families=ALL_FAMILIES)),
        )
    return _ENGINES[key]


@dataclass(frozen=True, slots=True)
class LiveContext:
    market_stale: bool
    symbol_active: bool


def evaluate_candle(
    v: Variant,
    analyzer: MarketAnalyzer,
    frames: list[MtfFrame],
    ctx: LiveContext,
    *,
    strategy_version: str,
    config: SignalConfig = DEFAULT_SIGNAL_CONFIG,
) -> SignalEvaluation:
    """Evaluation of the analyzer's LAST closed candle. Directional only for a trade."""
    snapshot = analyzer.snapshot(None, context=frames, generated_at=FIXED_TIME)
    bar = analyzer.series.last
    neutral = SignalEvaluation(
        symbol=snapshot.symbol,
        timeframe=snapshot.timeframe,
        candle_time=snapshot.candle_time,
        developing=False,
        signal_class=SignalClass.NEUTRAL,
        side=None,
        score=0.0,
        bull_score=0.0,
        bear_score=0.0,
        hypothesis=None,
        best_bull=None,
        best_bear=None,
        plan=None,
        neutral_reason=NEUTRAL_TEXT["no_trigger"],
        strategy_version=strategy_version,
    )
    inp = SignalInput(
        snapshot=snapshot,
        recent_bars=tuple(analyzer.series.tail(RECENT_BARS)),
        tick_size=analyzer.tick,
        market_stale=ctx.market_stale,
        symbol_active=ctx.symbol_active,
    )
    gate_engine, scoring_engine = _engines(config)
    gate = gate_engine._gate(inp)
    if gate is not None:
        return _replace(neutral, neutral_reason=gate)
    if not has_trigger(analyzer):
        return neutral
    hyps = research_hypotheses(scoring_engine, inp)
    ev, reason, pick = evaluate_hyps(
        v,
        symbol=snapshot.symbol,
        timeframe=snapshot.timeframe,
        tick=analyzer.tick,
        bar=bar,
        candle_time=snapshot.candle_time,
        hyps=hyps,
        gated=None,
        strategy_version=strategy_version,
    )
    if ev is not None:
        return ev
    if pick is None:
        return _replace(neutral, neutral_reason=reason if reason != REASON_GATED else gate)
    return _replace(
        neutral,
        neutral_reason=reason,
        score=pick.score,
        hypothesis=pick.record.hyp,
    )


def _replace(ev: SignalEvaluation, **changes: Any) -> SignalEvaluation:
    return replace(ev, **changes)
