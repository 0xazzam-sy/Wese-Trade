"""Displacement: how forcefully a candle moved. 0-100 strength, NOT a trade confidence.

score = 100 * (0.3 * body/range                     (only if the candle moves in `direction`)
             + 0.3 * min(1, range / ATR / range_full)
             + 0.2 * min(1, max(0, relvol - 1) / volume_full)
             + 0.2 * min(1, move / ATR / move_full))
ATR is the value BEFORE the candle, so a candle is never measured against itself.
"""

from __future__ import annotations

from app.analysis.config import AnalysisConfig
from app.analysis.indicators.stats import clamp
from app.analysis.series import Bar


def displacement_score(
    bar: Bar,
    atr: float | None,
    relative_volume: float | None,
    move: float,
    bullish: bool,
    config: AnalysisConfig,
) -> float:
    if bar.range <= 0:
        return 0.0
    with_direction = bar.bullish if bullish else bar.bearish
    body = bar.body / bar.range if with_direction else 0.0
    rng = clamp(bar.range / atr / config.displacement_range_full_atr, 0, 1) if atr else 0.0
    vol = (
        clamp((relative_volume - 1) / config.displacement_volume_full, 0, 1)
        if relative_volume is not None
        else 0.0
    )
    mv = clamp(abs(move) / atr / config.displacement_move_full_atr, 0, 1) if atr else 0.0
    return 100.0 * (0.3 * body + 0.3 * rng + 0.2 * vol + 0.2 * mv)
