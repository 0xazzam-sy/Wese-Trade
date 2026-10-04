"""Setup families: explicit triggers, eligibility and invalidation anchors.

A trade hypothesis can only arise from a STRUCTURE EVENT confirmed on the evaluated candle
(or, for developing signals, a developing break on the forming candle). This ties every
signal to one identifiable event (stable id, dedupe) and makes "confirmed at candle close"
exact.

Long setups (shorts mirror):
* TREND_CONTINUATION    trigger: internal bullish BOS.
                        needs: swing bullish, EMA trend not bearish, trending regime.
* PULLBACK_CONTINUATION trigger: internal bullish CHoCH.
                        needs: swing bullish, pullback reached value (discount/OTE/OB/FVG).
* BREAKOUT_CONTINUATION trigger: swing bullish BOS.
                        needs: displacement, relative volume, close not rejected,
                        higher timeframe not strongly bearish.
* LIQUIDITY_REVERSAL    trigger: internal (or swing) bullish CHoCH, or internal BOS.
                        needs: sell-side sweep within N bars, price back above the swept
                        level, sweep low not undercut since.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.analysis.enums import StructureLayer
from app.analysis.models import FairValueGap, OrderBlock
from app.signal_engine.enums import EntryModel, SetupFamily, Side
from app.signal_engine.models import Trigger
from app.signal_engine.scoring import (
    Ctx,
    aligned_sweep,
    supporting_blocks,
    supporting_gaps,
)


@dataclass(slots=True)
class Setup:
    family: SetupFamily
    side: Side
    trigger: Trigger
    stop_anchors: list[tuple[float, str]] = field(default_factory=list)
    entry_model: EntryModel = EntryModel.MARKET
    zone_edge: float | None = None  # retest level for ZONE_ENTRY


def triggers(ctx: Ctx, developing: bool) -> list[Trigger]:
    snap = ctx.snap
    out: list[Trigger] = []
    if not developing:
        for state in (snap.swing_structure, snap.internal_structure):
            if state is None:
                continue
            for e in state.events:
                if e.time == snap.candle_time:
                    out.append(
                        Trigger(
                            id=e.id,
                            time=e.time,
                            layer=e.layer.value,
                            type=e.type.value,
                            direction=e.direction.value,
                            displacement=e.displacement,
                            relative_volume=e.relative_volume,
                            level=e.level,
                        )
                    )
        return out
    dev = snap.developing
    candle = snap.forming_candle
    if dev is None or snap.forming_time is None:
        return out
    disp = None
    if candle is not None and candle.range_atr is not None:
        disp = 100 * candle.body_pct * min(1.0, candle.range_atr / 2)
    for b in (*dev.swing_breaks, *dev.internal_breaks):
        out.append(
            Trigger(
                id=f"dev:{b.layer.value}:{b.type.value}:{b.direction.value}:{snap.forming_time}",
                time=snap.forming_time,
                layer=b.layer.value,
                type=b.type.value,
                direction=b.direction.value,
                displacement=disp,
                relative_volume=None,
                level=b.level,
            )
        )
    return out


def _direction_after(ctx: Ctx, layer: StructureLayer, trigger: Trigger, side: Side) -> str | None:
    state = (
        ctx.snap.swing_structure if layer is StructureLayer.SWING else ctx.snap.internal_structure
    )
    if trigger.layer == layer.value:
        return side.direction  # the trigger itself sets this layer's direction
    return state.direction.value if state else None


def _pullback_reached_value(ctx: Ctx) -> str | None:
    bars = ctx.bars[-ctx.cfg.pullback_lookback_bars :]
    if not bars:
        return None
    pd = ctx.snap.premium_discount
    if pd is not None:
        if ctx.side is Side.LONG and min(b.low for b in bars) <= pd.equilibrium:
            return "discount"
        if ctx.side is Side.SHORT and max(b.high for b in bars) >= pd.equilibrium:
            return "premium"
    ote = ctx.snap.ote
    if ote is not None and ote.active and ctx.al(ote.direction.value) == 1:
        if ctx.side is Side.LONG and min(b.low for b in bars) <= ote.upper:
            return "ote"
        if ctx.side is Side.SHORT and max(b.high for b in bars) >= ote.lower:
            return "ote"
    zones: list[OrderBlock | FairValueGap] = [*supporting_blocks(ctx), *supporting_gaps(ctx)]
    for zone in zones:
        if ctx.side is Side.LONG and min(b.low for b in bars) <= zone.top:
            return "zone"
        if ctx.side is Side.SHORT and max(b.high for b in bars) >= zone.bottom:
            return "zone"
    return None


def _protected(ctx: Ctx, layer: StructureLayer) -> float | None:
    state = (
        ctx.snap.swing_structure if layer is StructureLayer.SWING else ctx.snap.internal_structure
    )
    if state is None:
        return None
    level = state.protected_low if ctx.side is Side.LONG else state.protected_high
    return level.price if level is not None and level.active else None


def _anchors(ctx: Ctx, items: list[tuple[float | None, str]]) -> list[tuple[float, str]]:
    """Keep anchors on the risk side of price (below for longs), in priority order."""
    out = []
    for price, source in items:
        if price is None:
            continue
        if ctx.side.sign * (ctx.price - price) > 0:
            out.append((price, source))
    return out


def _zone_entry(ctx: Ctx) -> float | None:
    """Nearest supporting zone edge between price and zone_entry_max_atr * ATR away."""
    edges = []
    zones: list[OrderBlock | FairValueGap] = [*supporting_blocks(ctx), *supporting_gaps(ctx)]
    for zone in zones:
        edge = zone.top if ctx.side is Side.LONG else zone.bottom
        gap = ctx.side.sign * (ctx.price - edge)
        if 0 < gap <= ctx.cfg.zone_entry_max_atr * ctx.atr:
            edges.append((gap, edge))
    return min(edges)[1] if edges else None


def evaluate_setups(ctx: Ctx, trig: Trigger) -> tuple[list[Setup], list[str]]:
    """Families this trigger can start for ctx.side, plus Arabic reasons for rejections."""
    side, cfg, snap = ctx.side, ctx.cfg, ctx.snap
    rejected: list[str] = []
    setups: list[Setup] = []
    if trig.direction != side.direction:
        return setups, rejected
    swing_dir = _direction_after(ctx, StructureLayer.SWING, trig, side)
    regime = snap.regime.directional.value if snap.regime else None
    opposite_trends = (
        {"downtrend", "strong_downtrend"} if side is Side.LONG else {"uptrend", "strong_uptrend"}
    )
    last_bar = ctx.bars[-1] if ctx.bars else None

    # TREND_CONTINUATION ---------------------------------------------------------------------
    if trig.layer == "internal" and trig.type == "BOS":
        if ctx.al(swing_dir) != 1:
            rejected.append("استمرار الاتجاه: الهيكل الرئيسي غير متوافق")
        elif snap.trend is not None and ctx.al(snap.trend.direction.value) == -1:
            rejected.append("استمرار الاتجاه: المتوسطات تعاكس الاتجاه")
        elif regime in opposite_trends or regime == "range":
            rejected.append("استمرار الاتجاه: حالة السوق غير مناسبة")
        else:
            setups.append(
                Setup(
                    SetupFamily.TREND_CONTINUATION,
                    side,
                    trig,
                    _anchors(
                        ctx,
                        [
                            (_protected(ctx, StructureLayer.INTERNAL), "internal_protected"),
                            (_protected(ctx, StructureLayer.SWING), "swing_protected"),
                        ],
                    ),
                )
            )

    # PULLBACK_CONTINUATION ------------------------------------------------------------------
    if trig.layer == "internal" and trig.type == "CHOCH":
        reached = _pullback_reached_value(ctx)
        if ctx.al(swing_dir) != 1:
            rejected.append("استمرار بعد تصحيح: الهيكل الرئيسي غير متوافق")
        elif reached is None:
            rejected.append("استمرار بعد تصحيح: التصحيح لم يصل إلى منطقة قيمة")
        elif regime in opposite_trends:
            rejected.append("استمرار بعد تصحيح: حالة السوق معاكسة")
        else:
            bars = ctx.bars[-cfg.pullback_lookback_bars :]
            extreme = min(b.low for b in bars) if side is Side.LONG else max(b.high for b in bars)
            edge = _zone_entry(ctx)
            setups.append(
                Setup(
                    SetupFamily.PULLBACK_CONTINUATION,
                    side,
                    trig,
                    _anchors(
                        ctx,
                        [
                            (extreme, "pullback_extreme"),
                            (_protected(ctx, StructureLayer.INTERNAL), "internal_protected"),
                            (_protected(ctx, StructureLayer.SWING), "swing_protected"),
                        ],
                    ),
                    EntryModel.ZONE if edge is not None else EntryModel.MARKET,
                    edge,
                )
            )

    # BREAKOUT_CONTINUATION -------------------------------------------------------------------
    if trig.layer == "swing" and trig.type == "BOS":
        candle = snap.forming_candle if trig.id.startswith("dev:") else snap.candle
        location = None
        if candle is not None:
            location = candle.close_location if side is Side.LONG else 1 - candle.close_location
        mtf = snap.multi_timeframe
        strong_opp = "strong_downtrend" if side is Side.LONG else "strong_uptrend"
        htf_block = any(
            f.ready and f.directional_regime and f.directional_regime.value == strong_opp
            for f in (mtf.higher if mtf else ())
        )
        if (trig.displacement or 0) < cfg.breakout_min_displacement:
            rejected.append("استمرار بعد اختراق: الاندفاع غير كافٍ")
        elif trig.relative_volume is not None and trig.relative_volume < cfg.breakout_min_relvol:
            rejected.append("استمرار بعد اختراق: الحجم لا يؤكد الاختراق")
        elif location is not None and location < cfg.breakout_min_close_location:
            rejected.append("استمرار بعد اختراق: رفض فوري للاختراق")
        elif htf_block:
            rejected.append("استمرار بعد اختراق: الإطار الأعلى معاكس بقوة")
        else:
            trigger_extreme = None
            if last_bar is not None and not trig.id.startswith("dev:"):
                trigger_extreme = last_bar.low if side is Side.LONG else last_bar.high
            setups.append(
                Setup(
                    SetupFamily.BREAKOUT_CONTINUATION,
                    side,
                    trig,
                    _anchors(
                        ctx,
                        [
                            (_protected(ctx, StructureLayer.INTERNAL), "internal_protected"),
                            (trigger_extreme, "breakout_candle"),
                            (_protected(ctx, StructureLayer.SWING), "swing_protected"),
                        ],
                    ),
                )
            )

    # LIQUIDITY_REVERSAL ------------------------------------------------------------------------
    if trig.type == "CHOCH" or (trig.layer == "internal" and trig.type == "BOS"):
        sweep = aligned_sweep(ctx, cfg.reversal_sweep_bars)
        if sweep is None:
            if trig.type == "CHOCH":
                rejected.append("انعكاس: لا يوجد سحب سيولة حديث")
        else:
            after = [b for b in ctx.bars if b.time > sweep.time]
            intact = (
                all(b.low > sweep.extreme for b in after)
                if side is Side.LONG
                else all(b.high < sweep.extreme for b in after)
            )
            back_inside = side.sign * (ctx.price - sweep.level) > 0
            if not back_inside:
                rejected.append("انعكاس: السعر لم يعد فوق/تحت المستوى المسحوب")
            elif not intact:
                rejected.append("انعكاس: تم كسر طرف السحب لاحقاً")
            else:
                setups.append(
                    Setup(
                        SetupFamily.LIQUIDITY_REVERSAL,
                        side,
                        trig,
                        _anchors(
                            ctx,
                            [
                                (sweep.extreme, "sweep_extreme"),
                                (_protected(ctx, StructureLayer.INTERNAL), "internal_protected"),
                            ],
                        ),
                    )
                )
    return setups, rejected
