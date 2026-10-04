"""Research pass 1: sequential replay that records EVERY hypothesis at every trigger candle.

Same loop and no-lookahead rules as `backtesting.runner.replay` (context candles are only
consumed once closed at or before the execution close). At each candle that confirmed a
structure event:

* the canonical `SignalEngine.evaluate` runs unchanged (baseline evaluation, for parity);
* every setup of every family and side is scored with the canonical `_score`, and plans
  are built with the canonical `build_plan` under a small, fixed set of plan models:

    entry   base  = the engine's own entry model (pullbacks may use a zone)
            close = always a market entry at the confirmation close
            zone  = limit at the nearest supporting OB/FVG edge (only if one exists)
    stop    A = structure anchors (the engine's)    B = aligned-sweep extreme first
            C = supporting order-block edge first   (B/C fall back to A's anchors)
    target  A = all structural candidates           B = liquidity-first (pools + swing levels)

* compact, side-adjusted features are stored for score research.

Pass 2 (`research.simulate`) re-selects hypotheses for each research variant and runs the
canonical `SignalTracker`. Nothing here changes MarketAnalyzer or SignalEngine semantics.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from app.analysis.config import DEFAULT_CONFIG as ANALYSIS_CONFIG
from app.analysis.engine import MarketAnalyzer
from app.analysis.multi_timeframe.context import context_timeframes
from app.analysis.series import Bar, to_bar
from app.market_data.models import Candle
from app.market_data.timeframes import Timeframe
from app.signal_engine.config import DEFAULT_SIGNAL_CONFIG, SignalConfig
from app.signal_engine.engine import SignalEngine
from app.signal_engine.enums import EntryModel, Side
from app.signal_engine.models import Hypothesis, SignalEvaluation, SignalInput, TradePlan
from app.signal_engine.rules import Setup, _anchors, _zone_entry, evaluate_setups, triggers
from app.signal_engine.runtime import FIXED_TIME, RECENT_BARS, has_trigger
from app.signal_engine.scoring import Ctx, aligned_sweep, ema_distance_atr, supporting_blocks
from app.signal_engine.trade_plan import PlanRejectedError, build_plan

ALL_FAMILIES = (
    "TREND_CONTINUATION",
    "PULLBACK_CONTINUATION",
    "BREAKOUT_CONTINUATION",
    "LIQUIDITY_REVERSAL",
)
PLAN_KEYS = ("base/A/A", "close/A/A", "zone/A/A", "base/B/A", "base/C/A", "base/A/B")
LIQUIDITY_TARGETS = frozenset({"liquidity", "swing_level"})
SWEEP_STOP_BARS = 20


@dataclass(slots=True)
class HypRecord:
    family: str
    side: str
    hyp: Hypothesis
    plans: dict[str, TradePlan | str]  # plan key -> plan, or the Arabic rejection reason
    features: dict[str, Any]


@dataclass(slots=True)
class TriggerRecord:
    index: int  # bar index of the confirming candle
    close_time: int
    baseline: SignalEvaluation
    hyps: list[HypRecord]  # engine order: LONG first, triggers in engine order
    events: list[tuple[str, str, str]]  # (layer, type, direction) confirmed on this candle
    gated: str | None = None


@dataclass(slots=True)
class SeriesResearch:
    symbol: str
    timeframe: str
    tick: float
    bars: list[Bar]
    triggers: list[TriggerRecord] = field(default_factory=list)
    signal_config: str = ""


def _plan(ctx: Ctx, setup: Setup, **kw: Any) -> TradePlan | str:
    try:
        return build_plan(ctx, setup, **kw)
    except PlanRejectedError as exc:
        return exc.reason


def plans_for(ctx: Ctx, setup: Setup) -> dict[str, TradePlan | str]:
    out: dict[str, TradePlan | str] = {"base/A/A": _plan(ctx, setup)}
    market = replace(setup, entry_model=EntryModel.MARKET, zone_edge=None)
    out["close/A/A"] = _plan(ctx, market)
    edge = _zone_entry(ctx)
    out["zone/A/A"] = (
        _plan(ctx, replace(setup, entry_model=EntryModel.ZONE, zone_edge=edge))
        if edge is not None
        else "no_zone"
    )
    sweep = aligned_sweep(ctx, SWEEP_STOP_BARS)
    sweep_anchor = _anchors(ctx, [(sweep.extreme if sweep else None, "sweep_extreme")])
    out["base/B/A"] = _plan(ctx, replace(setup, stop_anchors=[*sweep_anchor, *setup.stop_anchors]))
    blocks = supporting_blocks(ctx)
    ob_levels = [(b.bottom if ctx.side is Side.LONG else b.top, "order_block") for b in blocks]
    ob_anchor = sorted(_anchors(ctx, list(ob_levels)), key=lambda a: abs(ctx.price - a[0]))[:1]
    out["base/C/A"] = _plan(ctx, replace(setup, stop_anchors=[*ob_anchor, *setup.stop_anchors]))
    out["base/A/B"] = _plan(ctx, setup, target_filter=LIQUIDITY_TARGETS.__contains__)
    return out


def features(ctx: Ctx, setup: Setup) -> dict[str, Any]:
    """Side-adjusted facts (aligned = +1, opposed = -1) used by score research."""
    s = ctx.snap
    mtf = s.multi_timeframe
    frames = [f for f in (mtf.higher if mtf else ()) if f.ready]
    pd = s.premium_discount
    pos = None if pd is None else (pd.position if ctx.side is Side.LONG else 100 - pd.position)
    trend = s.trend
    vol = s.volatility
    candle = s.candle
    swing = s.swing_structure
    return {
        "regime": s.regime.directional.value if s.regime else None,
        "vol_regime": vol.regime.value if vol else None,
        "atr": ctx.atr,
        "atr_pct": (ctx.atr / ctx.price * 100) if ctx.price else None,
        "atr_percentile": vol.atr_percentile if vol else None,
        "htf1_trend": ctx.al(frames[0].trend.value if frames and frames[0].trend else None)
        if frames
        else None,
        "htf1_structure": ctx.al(
            frames[0].structure.value if frames and frames[0].structure else None
        )
        if frames
        else None,
        "htf_frames": len(frames),
        "swing": ctx.al(swing.direction.value if swing else None),
        "internal": ctx.al(s.internal_structure.direction.value if s.internal_structure else None),
        "trend_dir": ctx.al(trend.direction.value if trend else None),
        "trend_score": (ctx.side.sign * trend.score) if trend else None,
        "ema_dist_atr": ema_distance_atr(ctx),
        "pd_pos": pos,  # 0 = deepest discount for this side, 100 = most extended
        "ote": bool(
            s.ote and s.ote.active and s.ote.price_in_zone and ctx.al(s.ote.direction.value) == 1
        ),
        "ob_support": bool(supporting_blocks(ctx)),
        "rsi": None
        if s.momentum is None or s.momentum.rsi is None
        else (s.momentum.rsi if ctx.side is Side.LONG else 100 - s.momentum.rsi),
        "displacement": setup.trigger.displacement,
        "relvol": setup.trigger.relative_volume,
        "close_loc": None
        if candle is None
        else (candle.close_location if ctx.side is Side.LONG else 1 - candle.close_location),
        "sweep_recent": aligned_sweep(ctx, 10) is not None,
        "trigger": f"{setup.trigger.layer}:{setup.trigger.type}",
    }


def research_hypotheses(engine: SignalEngine, inp: SignalInput) -> list[HypRecord]:
    """Every family's hypothesis for both sides (engine order), with all plan models."""
    out: list[HypRecord] = []
    for side in (Side.LONG, Side.SHORT):
        ctx = Ctx(inp.snapshot, side, inp.recent_bars, inp.tick_size, engine.config)
        for trig in triggers(ctx, False):
            setups, _why = evaluate_setups(ctx, trig)
            for setup in setups:
                hyp = engine._score(ctx, setup)
                out.append(
                    HypRecord(
                        setup.family.value,
                        side.value,
                        hyp,
                        plans_for(ctx, setup),
                        features(ctx, setup),
                    )
                )
    return out


def collect(
    symbol: str,
    timeframe: Timeframe,
    candles: Sequence[Candle],
    context: Mapping[Timeframe, Sequence[Candle]],
    *,
    tick: float,
    config: SignalConfig = DEFAULT_SIGNAL_CONFIG,
) -> SeriesResearch:
    # All families are scored; baseline parity uses the engine's own enabled set.
    research_engine = SignalEngine(config.with_changes(enabled_families=ALL_FAMILIES))
    baseline_engine = SignalEngine(config)
    analyzer = MarketAnalyzer(symbol, timeframe, tick_size=tick, config=ANALYSIS_CONFIG)
    ctx_tfs = context_timeframes(timeframe)
    ctx_an = {
        tf: MarketAnalyzer(symbol, tf, tick_size=tick, config=ANALYSIS_CONFIG) for tf in ctx_tfs
    }
    ctx_pos = dict.fromkeys(ctx_tfs, 0)
    out = SeriesResearch(
        symbol, timeframe.value, tick, [to_bar(c, i) for i, c in enumerate(candles)]
    )
    out.signal_config = baseline_engine.version
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
        if not has_trigger(analyzer):
            continue
        bar = analyzer.series.last
        frames = [ctx_an[tf].frame() for tf in ctx_tfs]
        snapshot = analyzer.snapshot(None, context=frames, generated_at=FIXED_TIME)
        inp = SignalInput(
            snapshot=snapshot,
            recent_bars=tuple(analyzer.series.tail(RECENT_BARS)),
            tick_size=analyzer.tick,
        )
        baseline = baseline_engine.evaluate(inp)
        gate = baseline_engine._gate(inp)
        events = [
            (e.layer.value, e.type.value, e.direction.value)
            for st in (snapshot.swing_structure, snapshot.internal_structure)
            if st is not None
            for e in st.events
            if e.time == snapshot.candle_time
        ]
        hyps = [] if gate is not None else research_hypotheses(research_engine, inp)
        out.triggers.append(TriggerRecord(bar.index, bar.close_time, baseline, hyps, events, gate))
    return out
