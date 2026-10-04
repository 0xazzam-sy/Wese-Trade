"""Trade plan: entry zone, structure-aware stop, structural targets, R:R.

Entry
  MARKET_ENTRY: preferred = price at confirmation (trigger candle close).
  ZONE_ENTRY (pullbacks with a supporting zone edge within zone_entry_max_atr):
    entry zone = [zone edge, price]; preferred = its midpoint (a limit retest).
Stop
  First anchor (family priority order, e.g. sweep extreme / protected level) that lies on
  the risk side, minus buffer = max(stop_buffer_ticks * tick, stop_buffer_atr * ATR).
  Risk must be >= max(min_stop_atr * ATR, min_stop_ticks * tick, min_risk_cost_multiple *
  round-trip cost); a tighter structural stop is WIDENED to that floor (still beyond the
  structure). An anchor needing more than max_stop_atr * ATR is skipped; if none fits, the
  plan is rejected ("no rational stop") and the signal stays NEUTRAL.
Targets (long; short mirrors)
  Candidates above entry: active buy-side liquidity pools, swing/internal break highs,
  active bearish OB / FVG lower edges, the dealing-range high; each front-run by
  max(tick, target_front_run_atr * ATR). Candidates within tp_merge_rr are merged.
  TP1 = first candidate with R >= tp_min_rr if R <= tp1_max_structural_rr, else a 1R
  extension; TP2 = next candidate with R >= max(TP1 + 0.4, 1.5) (else extension);
  TP3 = next with R >= max(TP2 + 0.5, 2.0) (else extension). Extensions are labeled.
  Rejected if an opposing obstacle (bearish OB or swing high) sits within min_headroom_rr.
"""

from __future__ import annotations

from collections.abc import Callable
from itertools import pairwise

from app.analysis.enums import ZoneStatus, ZoneType
from app.signal_engine.enums import EntryModel, SetupFamily, Side
from app.signal_engine.models import Target, TradePlan
from app.signal_engine.rules import Setup
from app.signal_engine.scoring import Ctx


class PlanRejectedError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _target_candidates(ctx: Ctx, family: SetupFamily) -> list[tuple[float, str]]:
    s = ctx.snap
    long = ctx.side is Side.LONG
    out: list[tuple[float, str]] = []
    if s.liquidity is not None:
        side = "buy_side" if long else "sell_side"
        out += [
            (p.level, "liquidity")
            for p in s.liquidity.pools
            if p.status.value == "active" and p.side.value == side
        ]
    for state, name in (
        (s.swing_structure, "swing_level"),
        (s.internal_structure, "internal_level"),
    ):
        if state is None:
            continue
        level = state.break_high if long else state.break_low
        if level is not None:
            out.append((level, name))
    opposing_ob = ZoneType.BEARISH_OB if long else ZoneType.BULLISH_OB
    opposing_fvg = ZoneType.BEARISH_FVG if long else ZoneType.BULLISH_FVG
    live = (ZoneStatus.ACTIVE, ZoneStatus.MITIGATED)
    out += [
        (b.bottom if long else b.top, "order_block")
        for b in s.order_blocks
        if b.type is opposing_ob and b.status in live
    ]
    out += [
        (g.bottom if long else g.top, "fvg")
        for g in s.fair_value_gaps
        if g.type is opposing_fvg and g.status in live
    ]
    if s.premium_discount is not None and family is not SetupFamily.BREAKOUT_CONTINUATION:
        out.append((s.premium_discount.high if long else s.premium_discount.low, "range_extreme"))
    return out


def _obstacles(ctx: Ctx, family: SetupFamily) -> list[float]:
    s = ctx.snap
    long = ctx.side is Side.LONG
    out = []
    opposing_ob = ZoneType.BEARISH_OB if long else ZoneType.BULLISH_OB
    for b in s.order_blocks:
        if (
            b.type is opposing_ob
            and b.status in (ZoneStatus.ACTIVE, ZoneStatus.MITIGATED)
            and b.quality >= ctx.cfg.zone_min_quality
        ):
            out.append(b.bottom if long else b.top)
    if family is not SetupFamily.BREAKOUT_CONTINUATION and s.swing_structure is not None:
        level = s.swing_structure.break_high if long else s.swing_structure.break_low
        if level is not None:
            out.append(level)
    return out


def build_plan(
    ctx: Ctx, setup: Setup, *, target_filter: Callable[[str], bool] | None = None
) -> TradePlan:
    """`target_filter` (research only) keeps target candidates by source name; None = all."""
    cfg = ctx.cfg
    atr = ctx.atr
    if atr <= 0:
        raise PlanRejectedError("ATR غير متاح")
    sign = ctx.side.sign
    tick = ctx.tick or 0.0
    price = ctx.price

    # --- entry ----------------------------------------------------------------------------
    if setup.entry_model is EntryModel.ZONE and setup.zone_edge is not None:
        low, high = sorted((setup.zone_edge, price))
        preferred = (low + high) / 2
        model = EntryModel.ZONE
    else:
        low = high = preferred = price
        model = EntryModel.MARKET

    # --- stop -----------------------------------------------------------------------------
    buffer = max(cfg.stop_buffer_ticks * tick, cfg.stop_buffer_atr * atr)
    floor = max(
        cfg.min_stop_atr * atr,
        cfg.min_stop_ticks * tick,
        cfg.min_risk_cost_multiple * cfg.round_trip_cost_rate() * preferred,
    )
    ceiling = cfg.max_stop_atr * atr
    if floor > ceiling:
        raise PlanRejectedError("وقف الخسارة المنطقي أصغر من تكلفة التداول والضوضاء")
    stop = None
    source = ""
    for anchor, name in setup.stop_anchors:
        candidate = anchor - sign * buffer
        risk = sign * (preferred - candidate)
        if risk <= 0 or risk > ceiling:
            continue
        if risk < floor:
            candidate = preferred - sign * floor
            name = f"{name}+floor"
        stop, source = candidate, name
        break
    if stop is None:
        raise PlanRejectedError("لا يوجد وقف خسارة منطقي ضمن الحدود")
    risk = sign * (preferred - stop)

    # --- headroom ---------------------------------------------------------------------------
    for obstacle in _obstacles(ctx, setup.family):
        distance = sign * (obstacle - preferred)
        if 0 < distance < cfg.min_headroom_rr * risk:
            raise PlanRejectedError("مستوى معاكس قريب جداً من الدخول")

    # --- targets ---------------------------------------------------------------------------
    front = max(tick, cfg.target_front_run_atr * atr)
    raw = []
    for level, name in _target_candidates(ctx, setup.family):
        if target_filter is not None and not target_filter(name):
            continue
        price_t = level - sign * front
        rr = sign * (price_t - preferred) / risk
        if cfg.tp_min_rr <= rr <= cfg.tp_max_rr:
            raw.append((rr, price_t, name))
    raw.sort()
    merged: list[tuple[float, float, str]] = []
    for item in raw:
        if merged and item[0] - merged[-1][0] < cfg.tp_merge_rr:
            continue
        merged.append(item)

    def pick(min_rr: float, max_rr: float, fallback_rr: float) -> Target:
        for rr, p, name in merged:
            if min_rr <= rr <= max_rr:
                return Target(round_price(p, tick), round(rr, 2), name)
        p = preferred + sign * fallback_rr * risk
        return Target(round_price(p, tick), round(fallback_rr, 2), "extension")

    tp1 = pick(cfg.tp_min_rr, cfg.tp1_max_structural_rr, 1.0)
    tp2 = pick(max(tp1.rr + 0.4, 1.5), cfg.tp_max_rr, max(2.0, tp1.rr + 0.75))
    tp3 = pick(max(tp2.rr + 0.5, 2.0), cfg.tp_max_rr, max(3.0, tp2.rr + 1.0))
    targets = (tp1, tp2, tp3)
    prices = [preferred, *(t.price for t in targets)]
    if any(sign * (b - a) <= 0 for a, b in pairwise(prices)):
        raise PlanRejectedError("ترتيب الأهداف غير صالح")
    if tp2.rr < cfg.min_tp2_rr:
        raise PlanRejectedError("نسبة العائد إلى المخاطرة غير كافية")
    return TradePlan(
        entry_model=model,
        entry_low=round_price(low, tick),
        entry_high=round_price(high, tick),
        preferred_entry=round_price(preferred, tick),
        stop=round_price(stop, tick),
        invalidation=round_price(stop, tick),
        stop_source=source,
        risk=risk,
        risk_atr=round(risk / atr, 3),
        targets=targets,
    )


def round_price(value: float, tick: float) -> float:
    if tick <= 0:
        return float(f"{value:.10g}")
    return float(f"{round(value / tick) * tick:.10g}")
