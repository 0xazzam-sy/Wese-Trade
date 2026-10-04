from __future__ import annotations

import pytest

from app.analysis.config import DEFAULT_CONFIG
from app.analysis.enums import (
    DirectionalRegime,
    MarketRegime,
    StructureDirection,
    VolatilityRegime,
)
from app.analysis.indicators.state import IndicatorState
from app.analysis.regime.detector import directional_regime, primary_regime

BULL, BEAR, NEUTRAL = (
    StructureDirection.BULLISH,
    StructureDirection.BEARISH,
    StructureDirection.NEUTRAL,
)


@pytest.mark.parametrize(
    ("score", "structure", "er", "expected"),
    [
        (0.8, BULL, 0.5, DirectionalRegime.STRONG_UPTREND),
        (0.8, NEUTRAL, 0.5, DirectionalRegime.UPTREND),  # strong needs bullish structure
        (0.8, BULL, 0.1, DirectionalRegime.UPTREND),  # strong needs efficiency
        (0.3, BULL, 0.2, DirectionalRegime.UPTREND),
        (0.5, BEAR, 0.5, DirectionalRegime.TRANSITIONAL),  # EMAs up, structure broke down
        (-0.8, BEAR, 0.5, DirectionalRegime.STRONG_DOWNTREND),
        (-0.3, NEUTRAL, 0.2, DirectionalRegime.DOWNTREND),
        (0.05, NEUTRAL, 0.1, DirectionalRegime.RANGE),
        (0.05, NEUTRAL, 0.6, DirectionalRegime.TRANSITIONAL),  # flat EMAs, efficient move
    ],
)
def test_directional_regime(
    score: float, structure: StructureDirection, er: float, expected: DirectionalRegime
) -> None:
    assert directional_regime(score, structure, er, DEFAULT_CONFIG) is expected


def test_primary_regime_is_never_contradictory() -> None:
    assert (
        primary_regime(DirectionalRegime.UPTREND, VolatilityRegime.EXTREME) is MarketRegime.UPTREND
    )
    assert (
        primary_regime(DirectionalRegime.RANGE, VolatilityRegime.HIGH)
        is MarketRegime.HIGH_VOLATILITY
    )
    assert (
        primary_regime(DirectionalRegime.TRANSITIONAL, VolatilityRegime.LOW)
        is MarketRegime.LOW_VOLATILITY
    )
    assert primary_regime(DirectionalRegime.RANGE, VolatilityRegime.NORMAL) is MarketRegime.RANGING
    for d in DirectionalRegime:
        for v in VolatilityRegime:
            assert isinstance(primary_regime(d, v), MarketRegime)


def test_volatility_regime_is_percentile_based() -> None:
    state = IndicatorState(DEFAULT_CONFIG)
    assert state.volatility_regime(None) is VolatilityRegime.NORMAL
    assert state.volatility_regime(10) is VolatilityRegime.LOW
    assert state.volatility_regime(50) is VolatilityRegime.NORMAL
    assert state.volatility_regime(85) is VolatilityRegime.HIGH
    assert state.volatility_regime(97) is VolatilityRegime.EXTREME
