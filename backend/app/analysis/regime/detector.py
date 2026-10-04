"""Deterministic market-regime classifier.

Direction and volatility are classified on separate axes so that one enum never carries
contradictory states. `primary` is a single dominant label derived from both.
"""

from __future__ import annotations

from app.analysis.config import AnalysisConfig
from app.analysis.enums import (
    DirectionalRegime,
    MarketRegime,
    StructureDirection,
    VolatilityRegime,
)
from app.analysis.models import RegimeFeatures, TrendFeatures


def directional_regime(
    trend_score: float,
    structure: StructureDirection,
    efficiency: float | None,
    config: AnalysisConfig,
) -> DirectionalRegime:
    er = efficiency if efficiency is not None else 0.0
    if (
        trend_score >= config.strong_trend_score
        and er >= config.strong_trend_efficiency
        and structure is StructureDirection.BULLISH
    ):
        return DirectionalRegime.STRONG_UPTREND
    if (
        trend_score <= -config.strong_trend_score
        and er >= config.strong_trend_efficiency
        and structure is StructureDirection.BEARISH
    ):
        return DirectionalRegime.STRONG_DOWNTREND
    if trend_score >= config.trend_threshold and structure is not StructureDirection.BEARISH:
        return DirectionalRegime.UPTREND
    if trend_score <= -config.trend_threshold and structure is not StructureDirection.BULLISH:
        return DirectionalRegime.DOWNTREND
    if abs(trend_score) < config.trend_threshold and er < config.range_efficiency:
        return DirectionalRegime.RANGE
    return DirectionalRegime.TRANSITIONAL


def primary_regime(direction: DirectionalRegime, volatility: VolatilityRegime) -> MarketRegime:
    if direction in (DirectionalRegime.RANGE, DirectionalRegime.TRANSITIONAL):
        if volatility in (VolatilityRegime.HIGH, VolatilityRegime.EXTREME):
            return MarketRegime.HIGH_VOLATILITY
        if volatility is VolatilityRegime.LOW:
            return MarketRegime.LOW_VOLATILITY
        return (
            MarketRegime.RANGING
            if direction is DirectionalRegime.RANGE
            else MarketRegime.TRANSITIONAL
        )
    return {
        DirectionalRegime.STRONG_UPTREND: MarketRegime.STRONG_UPTREND,
        DirectionalRegime.UPTREND: MarketRegime.UPTREND,
        DirectionalRegime.DOWNTREND: MarketRegime.DOWNTREND,
        DirectionalRegime.STRONG_DOWNTREND: MarketRegime.STRONG_DOWNTREND,
    }[direction]


def detect_regime(
    trend: TrendFeatures,
    structure: StructureDirection,
    efficiency: float | None,
    volatility: VolatilityRegime,
    atr_percentile: float | None,
    range_compression: float | None,
    config: AnalysisConfig,
) -> RegimeFeatures:
    direction = directional_regime(trend.score, structure, efficiency, config)
    return RegimeFeatures(
        primary=primary_regime(direction, volatility),
        directional=direction,
        volatility=volatility,
        inputs={
            "trend_score": trend.score,
            "ema_alignment": trend.alignment_score,
            "ema50_slope_atr": trend.emas[1].normalized_slope if len(trend.emas) > 1 else None,
            "efficiency_ratio": efficiency,
            "swing_structure": structure.value,
            "atr_percentile": atr_percentile,
            "range_compression": range_compression,
        },
    )
