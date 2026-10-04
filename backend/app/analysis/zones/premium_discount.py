"""Premium / discount / equilibrium over the ACTIVE dealing range.

Dealing range (swing layer; falls back to the internal layer when swing has no structure):
  * bullish structure: protected low -> highest high since it (closed candles)
  * bearish structure: protected high -> lowest low since it
  * neutral: the most recent confirmed swing high and swing low
Never an arbitrary ancient range: it is re-anchored at every structure break.
Equilibrium = 50%; `equilibrium_band` around it is "equilibrium"; above = premium,
below = discount. `position` = price as % of the range (may be <0 or >100 outside it).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.analysis.config import AnalysisConfig
from app.analysis.enums import (
    PivotSide,
    PremiumDiscountZone,
    StructureDirection,
    StructureLayer,
)
from app.analysis.models import PremiumDiscount
from app.analysis.series import BarSeries
from app.analysis.structure.market_structure import StructureTracker


@dataclass(frozen=True, slots=True)
class DealingRange:
    layer: StructureLayer
    direction: StructureDirection
    high: float
    high_time: int
    low: float
    low_time: int


def dealing_range(tracker: StructureTracker, series: BarSeries) -> DealingRange | None:
    last = len(series) - 1
    if tracker.direction is StructureDirection.BULLISH and tracker.protected_low:
        p = tracker.protected_low
        bars = series.window(p.index, last)
        if not bars:
            return None
        top = max(bars, key=lambda b: (b.high, -b.index))
        return DealingRange(tracker.layer, tracker.direction, top.high, top.time, p.price, p.time)
    if tracker.direction is StructureDirection.BEARISH and tracker.protected_high:
        p = tracker.protected_high
        bars = series.window(p.index, last)
        if not bars:
            return None
        bottom = min(bars, key=lambda b: (b.low, b.index))
        return DealingRange(
            tracker.layer, tracker.direction, p.price, p.time, bottom.low, bottom.time
        )
    highs = [p for p in tracker.pivots if p.side is PivotSide.HIGH]
    lows = [p for p in tracker.pivots if p.side is PivotSide.LOW]
    if not highs or not lows or highs[-1].price <= lows[-1].price:
        return None
    return DealingRange(
        tracker.layer,
        tracker.direction,
        highs[-1].price,
        highs[-1].time,
        lows[-1].price,
        lows[-1].time,
    )


def premium_discount(rng: DealingRange, price: float, config: AnalysisConfig) -> PremiumDiscount:
    span = rng.high - rng.low
    eq = (rng.high + rng.low) / 2
    band = config.equilibrium_band * span
    position = (price - rng.low) / span * 100 if span > 0 else 50.0
    if price > rng.high:
        zone = PremiumDiscountZone.ABOVE_RANGE
    elif price < rng.low:
        zone = PremiumDiscountZone.BELOW_RANGE
    elif abs(price - eq) <= band:
        zone = PremiumDiscountZone.EQUILIBRIUM
    else:
        zone = PremiumDiscountZone.PREMIUM if price > eq else PremiumDiscountZone.DISCOUNT
    return PremiumDiscount(
        layer=rng.layer,
        high=rng.high,
        high_time=rng.high_time,
        low=rng.low,
        low_time=rng.low_time,
        equilibrium=eq,
        equilibrium_upper=eq + band,
        equilibrium_lower=eq - band,
        position=position,
        zone=zone,
    )
