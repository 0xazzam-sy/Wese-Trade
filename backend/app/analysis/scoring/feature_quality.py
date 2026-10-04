"""Feature QUALITY scores (0-100).

Quality describes how clean/significant a detected feature is (zone size, displacement,
volume, alignment, freshness, mitigation). It is NOT a probability of profit and must never
be presented as one.
"""

from __future__ import annotations

from app.analysis.enums import StructureLayer, ZoneStatus
from app.analysis.indicators.stats import clamp

FRESHNESS_BARS = 200


def freshness(age: int) -> float:
    return clamp(1.0 - age / FRESHNESS_BARS, 0, 1)


def _volume_component(relative_volume: float | None) -> float:
    return clamp((relative_volume - 1.0) / 1.5, 0, 1) if relative_volume is not None else 0.0


def fvg_quality(
    size_atr: float,
    displacement: float,
    relative_volume: float | None,
    aligned: bool,
    age: int,
    status: ZoneStatus,
    filled: float,
) -> float:
    if status in (ZoneStatus.INVALIDATED, ZoneStatus.EXPIRED):
        return 0.0
    score = (
        25 * clamp(size_atr / 1.0, 0, 1)
        + 25 * displacement / 100
        + 15 * _volume_component(relative_volume)
        + 15 * (1.0 if aligned else 0.0)
        + 10 * freshness(age)
        + 10 * (1.0 - clamp(filled, 0, 1))
    )
    return round(score, 1)


def order_block_quality(
    displacement: float,
    relative_volume: float | None,
    layer: StructureLayer,
    height_atr: float | None,
    age: int,
    touches: int,
    status: ZoneStatus,
) -> float:
    if status in (ZoneStatus.INVALIDATED, ZoneStatus.EXPIRED):
        return 0.0
    compact = clamp(1.5 / height_atr, 0, 1) if height_atr else 0.5  # tall blocks are vaguer
    score = (
        35 * displacement / 100
        + 15 * _volume_component(relative_volume)
        + 15 * (1.0 if layer is StructureLayer.SWING else 0.5)
        + 10 * compact
        + 15 * freshness(age)
        + 10 * clamp(1.0 - touches / 3, 0, 1)
    )
    return round(score, 1)


def sweep_quality(
    rejection: float,
    inside_atr: float | None,
    penetration_atr: float | None,
    touches: int,
    relative_volume: float | None,
) -> float:
    # A clean sweep pokes moderately beyond (<= ~1 ATR) and closes well back inside.
    depth = 1.0 if penetration_atr is None else clamp(1.5 - penetration_atr, 0, 1)
    score = (
        35 * clamp(rejection, 0, 1)
        + 20 * (clamp(inside_atr / 0.5, 0, 1) if inside_atr is not None else 0.0)
        + 15 * depth
        + 15 * clamp((touches - 1) / 2, 0, 1)
        + 15 * _volume_component(relative_volume)
    )
    return round(score, 1)


def equal_level_strength(touches: int, spread: float, tolerance: float) -> float:
    tight = clamp(1.0 - spread / tolerance, 0, 1) if tolerance > 0 else 1.0
    return round(clamp(40 + 20 * (touches - 2) + 20 * tight, 0, 100), 1)
