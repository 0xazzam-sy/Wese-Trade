"""Raw candle-shape features and a deliberately small set of named patterns."""

from __future__ import annotations

from app.analysis.enums import FeatureStatus
from app.analysis.models import CandleFeatures
from app.analysis.series import Bar

STRONG_BODY = 0.7  # body >= 70% of range
PIN_WICK_BODY = 2.0  # rejection wick >= 2x body
PIN_WICK_RANGE = 0.6  # and >= 60% of range


def candle_features(
    bar: Bar, prev: Bar | None, atr: float | None, status: FeatureStatus
) -> CandleFeatures:
    rng = bar.range
    if rng <= 0:
        return CandleFeatures(bar.time, status, "flat", 0.0, 0.0, 0.0, 0.0, 0.5, ())
    body = bar.body
    upper = bar.high - max(bar.open, bar.close)
    lower = min(bar.open, bar.close) - bar.low
    patterns: list[str] = []
    if prev is not None:
        if (
            prev.bearish
            and bar.bullish
            and bar.close >= prev.open
            and bar.open <= prev.close
            and body > prev.body
        ):
            patterns.append("bullish_engulfing")
        if (
            prev.bullish
            and bar.bearish
            and bar.close <= prev.open
            and bar.open >= prev.close
            and body > prev.body
        ):
            patterns.append("bearish_engulfing")
        if bar.high < prev.high and bar.low > prev.low:
            patterns.append("inside_bar")
    if lower >= PIN_WICK_BODY * body and lower >= PIN_WICK_RANGE * rng:
        patterns.append("bullish_pin")
    if upper >= PIN_WICK_BODY * body and upper >= PIN_WICK_RANGE * rng:
        patterns.append("bearish_pin")
    if body >= STRONG_BODY * rng and (atr is None or rng >= atr):
        patterns.append("strong_body")
    direction = "up" if bar.bullish else "down" if bar.bearish else "flat"
    return CandleFeatures(
        time=bar.time,
        status=status,
        direction=direction,
        body_pct=body / rng,
        upper_wick_pct=upper / rng,
        lower_wick_pct=lower / rng,
        range_atr=rng / atr if atr else None,
        close_location=(bar.close - bar.low) / rng,
        patterns=tuple(patterns),
    )
