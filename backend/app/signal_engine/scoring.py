"""Component scores (0..1 each), category caps and conflict penalties.

Design rules:
* Bull and bear hypotheses are scored INDEPENDENTLY (bear is never 100 - bull).
* Each category yields one normalized value; weights live in config.Weights.
* Correlated evidence is capped: displacement + volume + candle describe the same trigger
  candle (trigger_cluster_cap); discount + OTE describe the same location (location cap).
* Penalties are explicit, named, deterministic point deductions.
* score = 100 * Σ points / Σ weights(available categories) - Σ penalties, clamped 0..100.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis.enums import StructureLayer, ZoneStatus, ZoneType
from app.analysis.indicators.stats import clamp
from app.analysis.models import (
    AnalysisSnapshot,
    FairValueGap,
    LiquiditySweep,
    OrderBlock,
    StructureEvent,
)
from app.analysis.series import Bar
from app.signal_engine import reasons as r
from app.signal_engine.config import SignalConfig
from app.signal_engine.enums import SetupFamily, Side
from app.signal_engine.models import Component, Penalty, Trigger

TF_SECONDS = {"1m": 60, "5m": 300, "10m": 600, "15m": 900, "30m": 1800, "1h": 3600}


@dataclass(frozen=True, slots=True)
class Ctx:
    snap: AnalysisSnapshot
    side: Side
    bars: tuple[Bar, ...]
    tick: float
    cfg: SignalConfig

    @property
    def step(self) -> int:
        return TF_SECONDS.get(self.snap.timeframe, 60)

    @property
    def atr(self) -> float:
        return self.snap.volatility.atr if self.snap.volatility else 0.0

    @property
    def price(self) -> float:
        return float(self.snap.price or 0.0)

    @property
    def now(self) -> int:
        return int(self.snap.forming_time or self.snap.candle_time or 0)

    def bars_ago(self, time: int) -> int:
        return max(0, (self.now - time) // self.step)

    def al(self, direction: str | None) -> int:
        """+1 aligned with this side, -1 opposed, 0 neutral/unknown."""
        if direction == self.side.direction:
            return 1
        if direction == self.side.opposite.direction:
            return -1
        return 0


@dataclass(slots=True)
class Scored:
    components: list[Component]
    penalties: list[Penalty]
    positive: list[str]
    negative: list[str]

    def add(self, name: str, value: float, weight: float) -> None:
        self.components.append(
            Component(name, clamp(value, 0, 1), weight, clamp(value, 0, 1) * weight)
        )

    def penalize(self, code: str, points: float, reason: str) -> None:
        if points > 0:
            self.penalties.append(Penalty(code, points, reason))
            self.negative.append(reason)


# --- evidence helpers -------------------------------------------------------------------
def recent_events(ctx: Ctx, layer: StructureLayer, within: int) -> list[StructureEvent]:
    state = (
        ctx.snap.swing_structure if layer is StructureLayer.SWING else ctx.snap.internal_structure
    )
    if state is None:
        return []
    return [e for e in state.events if ctx.bars_ago(e.time) <= within]


def aligned_sweep(ctx: Ctx, within: int) -> LiquiditySweep | None:
    """Most recent sweep of the liquidity OPPOSITE to this side (sell-side for a long)."""
    liq = ctx.snap.liquidity
    if liq is None:
        return None
    wanted = "sell_side" if ctx.side is Side.LONG else "buy_side"
    found = [s for s in liq.sweeps if s.side.value == wanted and ctx.bars_ago(s.time) <= within]
    return found[-1] if found else None


def adverse_sweep(ctx: Ctx, within: int) -> LiquiditySweep | None:
    liq = ctx.snap.liquidity
    if liq is None:
        return None
    wanted = "buy_side" if ctx.side is Side.LONG else "sell_side"
    found = [s for s in liq.sweeps if s.side.value == wanted and ctx.bars_ago(s.time) <= within]
    return found[-1] if found else None


def touched(ctx: Ctx, top: float, bottom: float) -> bool:
    """Did the last few closed bars trade into [bottom, top] without closing through it?"""
    bars = ctx.bars[-ctx.cfg.touch_lookback_bars :]
    if not bars:
        return False
    tol = 0.1 * ctx.atr
    if ctx.side is Side.LONG:
        return min(b.low for b in bars) <= top + tol and bars[-1].close >= bottom - tol
    return max(b.high for b in bars) >= bottom - tol and bars[-1].close <= top + tol


def supporting_blocks(ctx: Ctx) -> list[OrderBlock]:
    kind = ZoneType.BULLISH_OB if ctx.side is Side.LONG else ZoneType.BEARISH_OB
    return [
        b
        for b in ctx.snap.order_blocks
        if b.type is kind
        and b.status in (ZoneStatus.ACTIVE, ZoneStatus.MITIGATED)
        and b.quality >= ctx.cfg.zone_min_quality
    ]


def supporting_gaps(ctx: Ctx) -> list[FairValueGap]:
    kind = ZoneType.BULLISH_FVG if ctx.side is Side.LONG else ZoneType.BEARISH_FVG
    return [
        g
        for g in ctx.snap.fair_value_gaps
        if g.type is kind
        and g.status in (ZoneStatus.ACTIVE, ZoneStatus.MITIGATED)
        and g.filled <= ctx.cfg.fvg_max_filled
    ]


def ema_distance_atr(ctx: Ctx) -> float:
    trend = ctx.snap.trend
    if trend is None or not ctx.atr:
        return 0.0
    return ctx.side.sign * (ctx.price - trend.emas[0].value) / ctx.atr


# --- components ---------------------------------------------------------------------------
def score_htf(ctx: Ctx, out: Scored) -> None:
    mtf = ctx.snap.multi_timeframe
    frames = [f for f in (mtf.higher if mtf else ()) if f.ready]
    if not frames:
        return  # not available: excluded from normalization (e.g. 1h has no higher frame)
    weights = [0.6, 0.4] if len(frames) == 2 else [1.0]
    value = 0.0
    aligned: list[str] = []
    for frame, w in zip(frames, weights, strict=False):
        trend = ctx.al(frame.trend.value if frame.trend else None)
        structure = ctx.al(frame.structure.value if frame.structure else None)
        v = 0.5 * trend + 0.5 * structure
        value += w * v
        if v > 0:
            aligned.append(frame.timeframe)
    out.add("htf", (value + 1) / 2, ctx.cfg.weights.htf)
    if aligned:
        out.positive.append(r.htf_aligned(aligned, ctx.side))


def score_structure(ctx: Ctx, out: Scored, family: SetupFamily) -> None:
    swing = ctx.snap.swing_structure
    internal = ctx.snap.internal_structure
    s = ctx.al(swing.direction.value if swing else None)
    i = ctx.al(internal.direction.value if internal else None)
    swing_value = {1: 1.0, 0: 0.5, -1: 0.0}[s]
    if family is SetupFamily.LIQUIDITY_REVERSAL and s == -1:
        swing_value = 0.25  # a reversal starts against swing structure; weaker, not banned
    value = 0.6 * swing_value + 0.4 * {1: 1.0, 0: 0.5, -1: 0.0}[i]
    choch = [
        e
        for e in recent_events(ctx, StructureLayer.SWING, ctx.cfg.recent_swing_choch_bars)
        if e.type.value == "CHOCH" and ctx.al(e.direction.value) == 1
    ]
    if choch:
        value += 0.2
        out.positive.append(r.structure_event("swing", "CHOCH", ctx.side))
    out.add("structure", value, ctx.cfg.weights.structure)
    if s == 1:
        out.positive.append(f"الهيكل الرئيسي {r.side_word(ctx.side)}")
    elif s == -1:
        out.negative.append(f"الهيكل الرئيسي {r.DIR_AR[ctx.side.opposite.direction]}")
    if s == 1 and i == -1:
        out.negative.append("الهيكل الداخلي في تصحيح معاكس")


def score_liquidity(ctx: Ctx, out: Scored, family: SetupFamily) -> None:
    cfg = ctx.cfg
    sweep = aligned_sweep(ctx, cfg.reversal_sweep_bars)
    value = 0.3 if family is not SetupFamily.LIQUIDITY_REVERSAL else 0.0
    if sweep is not None:
        responded = sweep.structure_response is not None
        if responded:
            value = max(value, 0.6 + 0.4 * sweep.quality / 100)
            out.positive.append(r.SWEEP_FOR[ctx.side])
        else:
            value = max(value, 0.35 * sweep.quality / 100 + 0.2)
    liq = ctx.snap.liquidity
    if liq is not None and ctx.atr:
        ahead = liq.nearest_buy_side if ctx.side is Side.LONG else liq.nearest_sell_side
        if ahead is not None and abs(ahead - ctx.price) <= cfg.target_liquidity_atr * ctx.atr:
            value += 0.2
            out.positive.append("توجد سيولة مستهدفة قريبة في اتجاه الصفقة")
    out.add("liquidity", value, cfg.weights.liquidity)


def score_location(ctx: Ctx, out: Scored, family: SetupFamily) -> None:
    cfg = ctx.cfg
    if family is SetupFamily.BREAKOUT_CONTINUATION:
        d = ema_distance_atr(ctx)
        value = 1.0 if d <= 1.5 else clamp(1.0 - (d - 1.5) / 1.5 * 0.8, 0, 1)
        out.add("location", value, cfg.weights.location)
        if value >= 0.8:
            out.positive.append("الاختراق غير ممتد بشكل مفرط")
        return
    pd = ctx.snap.premium_discount
    ote = ctx.snap.ote
    value = 0.0
    good_half = "discount" if ctx.side is Side.LONG else "premium"
    if pd is not None:
        if pd.zone.value == good_half:
            value += 0.35
            out.positive.append(
                "السعر ضمن منطقة الخصم (Discount)"
                if ctx.side is Side.LONG
                else "السعر ضمن منطقة العلاوة (Premium)"
            )
        elif pd.zone.value == "equilibrium":
            value += 0.2
    if ote is not None and ote.active and ote.price_in_zone and ctx.al(ote.direction.value) == 1:
        value += 0.25
        out.positive.append("السعر داخل منطقة OTE")
    value = min(value, 0.45)  # discount and OTE describe the same retracement
    blocks = [b for b in supporting_blocks(ctx) if touched(ctx, b.top, b.bottom)]
    if blocks:
        best = max(blocks, key=lambda b: b.quality)
        value += 0.35 * best.quality / 100
        out.positive.append(
            "السعر داخل Bullish Order Block"
            if ctx.side is Side.LONG
            else "السعر داخل Bearish Order Block"
        )
    gaps = [g for g in supporting_gaps(ctx) if touched(ctx, g.top, g.bottom)]
    if gaps:
        best_gap = max(gaps, key=lambda g: g.quality)
        value += 0.2 * best_gap.quality / 100
        out.positive.append("السعر داخل فجوة قيمة عادلة داعمة (FVG)")
    out.add("location", value, cfg.weights.location)


def score_trend(ctx: Ctx, out: Scored) -> None:
    trend = ctx.snap.trend
    if trend is None:
        return
    value = (ctx.side.sign * trend.score + 1) / 2
    if trend.stack.value == ctx.side.direction:
        value += 0.1
    out.add("trend", value, ctx.cfg.weights.trend)
    if ctx.al(trend.direction.value) == 1:
        out.positive.append(f"اتجاه المتوسطات {r.side_word(ctx.side)}")
    elif ctx.al(trend.direction.value) == -1:
        out.negative.append("المتوسطات المتحركة تعاكس الاتجاه")


def score_trigger_cluster(ctx: Ctx, out: Scored, trigger: Trigger) -> None:
    w = ctx.cfg.weights
    displacement = (trigger.displacement or 0.0) / 100
    rel = trigger.relative_volume
    volume = clamp((rel - 0.7) / 1.3, 0, 1) if rel is not None else 0.4
    candle_value = 0.2
    candle = ctx.snap.forming_candle if trigger.id.startswith("dev:") else ctx.snap.candle
    if candle is not None:
        bullish_patterns = {"bullish_engulfing", "bullish_pin"}
        bearish_patterns = {"bearish_engulfing", "bearish_pin"}
        mine = bullish_patterns if ctx.side is Side.LONG else bearish_patterns
        good_dir = (
            (candle.direction == "up") if ctx.side is Side.LONG else (candle.direction == "down")
        )
        location = candle.close_location if ctx.side is Side.LONG else 1 - candle.close_location
        if mine & set(candle.patterns) or ("strong_body" in candle.patterns and good_dir):
            candle_value = 1.0
            out.positive.append("شمعة تأكيد قوية")
        elif location >= 0.7:
            candle_value = 0.6
    parts = [
        ("displacement", displacement, w.displacement),
        ("volume", volume, w.volume),
        ("candle", candle_value, w.candle),
    ]
    # The three describe ONE candle: together they are worth at most `trigger_cluster_cap`.
    raw_weight = sum(wt for _, _, wt in parts)
    scale = min(1.0, w.trigger_cluster_cap / raw_weight) if raw_weight > 0 else 1.0
    for name, v, wt in parts:
        out.add(name, v, wt * scale)
    if displacement >= 0.6:
        out.positive.append("اندفاع سعري قوي (Displacement)")
    if rel is not None and rel >= 1.5:
        out.positive.append("حجم التداول أعلى من المتوسط")


def score_momentum(ctx: Ctx, out: Scored) -> None:
    m = ctx.snap.momentum
    if m is None or m.rsi is None:
        return
    rsi = m.rsi if ctx.side is Side.LONG else 100 - m.rsi
    if 50 <= rsi <= 70:
        value = 1.0
    elif 45 <= rsi < 50 or 70 < rsi <= 80:
        value = 0.6
    elif rsi > 80:
        value = 0.3
    else:
        value = 0.1
    slope = (m.rsi_slope or 0.0) * ctx.side.sign
    if slope > 0:
        value += 0.2
    if m.divergence == ctx.side.direction:
        value += 0.3
        out.positive.append("انحراف RSI داعم")
    out.add("momentum", value, ctx.cfg.weights.momentum)
    if value < 0.3:
        out.negative.append(f"يوجد تعارض مع زخم {r.tf(ctx.snap.timeframe)}")


# --- penalties -------------------------------------------------------------------------------
def apply_penalties(ctx: Ctx, out: Scored, family: SetupFamily, trigger: Trigger) -> None:
    cfg, p = ctx.cfg, ctx.cfg.penalties
    mtf = ctx.snap.multi_timeframe
    frames = [f for f in (mtf.higher if mtf else ()) if f.ready]
    strong_opposite = "strong_downtrend" if ctx.side is Side.LONG else "strong_uptrend"
    strong_frames = [
        f for f in frames if f.directional_regime and f.directional_regime.value == strong_opposite
    ]
    if strong_frames:
        swing_choch = any(
            e.type.value == "CHOCH" and ctx.al(e.direction.value) == 1
            for e in recent_events(ctx, StructureLayer.SWING, cfg.recent_swing_choch_bars)
        )
        points = (
            p.htf_strong_opposition_reversal
            if family is SetupFamily.LIQUIDITY_REVERSAL and swing_choch
            else p.htf_strong_opposition
        )
        frame = strong_frames[-1]
        out.penalize(
            "htf_strong_opposition",
            points,
            r.htf_opposed(frame.timeframe, ctx.side.opposite.direction),
        )
    elif frames:
        first = frames[0]
        if (
            ctx.al(first.trend.value if first.trend else None) == -1
            and ctx.al(first.structure.value if first.structure else None) == -1
        ):
            out.penalize(
                "htf_first_opposed",
                p.htf_first_opposed,
                r.htf_opposed(first.timeframe, ctx.side.opposite.direction),
            )

    pd = ctx.snap.premium_discount
    if pd is not None and family is not SetupFamily.BREAKOUT_CONTINUATION:
        if ctx.side is Side.LONG and pd.position >= cfg.extreme_premium_position:
            out.penalize("extreme_location", p.extreme_location, "شراء في أعلى منطقة العلاوة")
        if ctx.side is Side.SHORT and pd.position <= cfg.extreme_discount_position:
            out.penalize("extreme_location", p.extreme_location, "بيع في أعمق منطقة الخصم")
    if ema_distance_atr(ctx) > cfg.overextension_atr:
        out.penalize("overextended", p.overextended, "السعر ممتد بعيداً عن المتوسط")
    vol = ctx.snap.volatility
    if vol is not None and vol.regime.value == "extreme":
        out.penalize("extreme_volatility", p.extreme_volatility, "تذبذب مرتفع جداً")
    rel = trigger.relative_volume
    if rel is not None and rel < 0.6:
        points = (
            p.volume_contradiction_breakout
            if family is SetupFamily.BREAKOUT_CONTINUATION
            else p.volume_contradiction
        )
        out.penalize("volume_contradiction", points, "حجم التداول ضعيف عند الإشارة")
    m = ctx.snap.momentum
    if m is not None and m.rsi is not None:
        rsi = m.rsi if ctx.side is Side.LONG else 100 - m.rsi
        if rsi < 40 and (m.rsi_slope or 0.0) * ctx.side.sign < 0:
            out.penalize(
                "momentum_opposed",
                p.momentum_opposed,
                f"يوجد تعارض مع زخم {r.tf(ctx.snap.timeframe)}",
            )
        if m.divergence == ctx.side.opposite.direction:
            out.penalize("opposite_divergence", p.opposite_divergence, "انحراف RSI معاكس")
    if adverse_sweep(ctx, cfg.adverse_sweep_bars) is not None:
        out.penalize("adverse_sweep", p.adverse_sweep, r.ADVERSE_SWEEP[ctx.side])
    opposing = ZoneType.BEARISH_OB if ctx.side is Side.LONG else ZoneType.BULLISH_OB
    for block in ctx.snap.order_blocks:
        if block.type is not opposing or block.status not in (
            ZoneStatus.ACTIVE,
            ZoneStatus.MITIGATED,
        ):
            continue
        if block.quality < cfg.zone_min_quality or not ctx.atr:
            continue
        edge = block.bottom if ctx.side is Side.LONG else block.top
        gap = ctx.side.sign * (edge - ctx.price)
        if 0 <= gap <= 0.5 * ctx.atr:
            out.penalize(
                "opposing_zone_ahead", p.opposing_zone_ahead, "منطقة Order Block معاكسة قريبة جداً"
            )
            break
    regime = ctx.snap.regime
    if (
        regime is not None
        and regime.directional.value == "transitional"
        and family
        in (
            SetupFamily.TREND_CONTINUATION,
            SetupFamily.PULLBACK_CONTINUATION,
        )
    ):
        out.penalize("transitional_regime", p.transitional_regime, "السوق في مرحلة انتقالية")


def finalize(out: Scored) -> tuple[float, float]:
    """(base score before penalties, final score), both 0-100."""
    available = sum(c.weight for c in out.components)
    points = sum(c.points for c in out.components)
    base = 100.0 * points / available if available else 0.0
    final = clamp(base - sum(p.points for p in out.penalties), 0, 100)
    return round(base, 2), round(final, 2)
