"""Optimal Trade Entry (OTE) zone — a retracement ZONE, not a signal.

Uses the active impulse of the dealing range (premium_discount.dealing_range):
  * bullish structure: impulse = protected low -> leg high; the OTE is the retracement
    band [high - ote_end * span, high - ote_start * span] (default 61.8%-79%, focus 70.5%)
  * bearish structure: impulse = protected high -> leg low; band measured upward
Active while the structure keeps its direction (a CHoCH re-anchors or removes it).
Neutral structure has no impulse, so no OTE.
"""

from __future__ import annotations

from app.analysis.config import AnalysisConfig
from app.analysis.enums import StructureDirection
from app.analysis.models import OteZone
from app.analysis.zones.premium_discount import DealingRange


def ote_zone(rng: DealingRange, price: float, config: AnalysisConfig) -> OteZone | None:
    span = rng.high - rng.low
    if span <= 0 or rng.direction is StructureDirection.NEUTRAL:
        return None
    if rng.direction is StructureDirection.BULLISH:
        upper = rng.high - config.ote_start * span
        lower = rng.high - config.ote_end * span
        focus = rng.high - config.ote_focus * span
        start, start_time, end, end_time = rng.low, rng.low_time, rng.high, rng.high_time
        active = price > rng.low
    else:
        lower = rng.low + config.ote_start * span
        upper = rng.low + config.ote_end * span
        focus = rng.low + config.ote_focus * span
        start, start_time, end, end_time = rng.high, rng.high_time, rng.low, rng.low_time
        active = price < rng.high
    return OteZone(
        direction=rng.direction,
        layer=rng.layer,
        impulse_start=start,
        impulse_start_time=start_time,
        impulse_end=end,
        impulse_end_time=end_time,
        upper=upper,
        lower=lower,
        focus=focus,
        active=active,
        price_in_zone=lower <= price <= upper,
    )
