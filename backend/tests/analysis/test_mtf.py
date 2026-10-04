from __future__ import annotations

import pytest

from app.analysis.enums import (
    DirectionalRegime,
    MtfAlignment,
    StructureDirection,
    TrendDirection,
    VolatilityRegime,
)
from app.analysis.models import MtfFrame
from app.analysis.multi_timeframe.context import align, build_context, context_timeframes
from app.market_data.timeframes import Timeframe


def test_mtf_mapping() -> None:
    m = Timeframe
    assert context_timeframes(m.M1) == (m.M5, m.M15)
    assert context_timeframes(m.M5) == (m.M15, m.H1)
    assert context_timeframes(m.M10) == (m.M30, m.H1)
    assert context_timeframes(m.M15) == (m.M30, m.H1)
    assert context_timeframes(m.M30) == (m.H1,)
    assert context_timeframes(m.H1) == ()  # no fabricated 4h


@pytest.mark.parametrize(
    ("execution", "higher", "expected"),
    [
        ("bullish", ["bullish", "bullish"], MtfAlignment.STRONG_BULLISH),
        ("bearish", ["bearish"], MtfAlignment.STRONG_BEARISH),
        ("bullish", ["bullish", "neutral"], MtfAlignment.BULLISH),
        ("bearish", ["neutral", "neutral"], MtfAlignment.BEARISH),
        ("bullish", ["bearish", "bearish"], MtfAlignment.COUNTERTREND),
        ("bullish", ["bearish", "neutral"], MtfAlignment.COUNTERTREND),
        ("bullish", ["bullish", "bearish"], MtfAlignment.MIXED),
        ("neutral", ["bullish", "bullish"], MtfAlignment.NEUTRAL),
        ("bullish", [], MtfAlignment.UNAVAILABLE),
        ("bullish", [None, None], MtfAlignment.UNAVAILABLE),
        ("bullish", ["bullish", None], MtfAlignment.STRONG_BULLISH),
    ],
)
def test_alignment_rules(execution: str, higher: list[str | None], expected: MtfAlignment) -> None:
    assert align(execution, higher) is expected


def _frame(tf: str, trend: TrendDirection, regime: DirectionalRegime) -> MtfFrame:
    structure = StructureDirection(trend.value)
    return MtfFrame(tf, True, 0, trend, structure, regime, VolatilityRegime.NORMAL)


def test_build_context_example_from_spec() -> None:
    bull, bear = TrendDirection.BULLISH, TrendDirection.BEARISH
    ctx = build_context(
        _frame("5m", bull, DirectionalRegime.UPTREND),
        [
            _frame("15m", bear, DirectionalRegime.DOWNTREND),
            _frame("1h", bear, DirectionalRegime.STRONG_DOWNTREND),
        ],
    )
    assert ctx.directional_alignment is MtfAlignment.COUNTERTREND
    assert ctx.structure_alignment is MtfAlignment.COUNTERTREND
    assert ctx.regime_alignment is MtfAlignment.COUNTERTREND
    assert ctx.volatility_aligned is True
    aligned = build_context(
        _frame("5m", bull, DirectionalRegime.UPTREND),
        [
            _frame("15m", bull, DirectionalRegime.UPTREND),
            _frame("1h", bull, DirectionalRegime.RANGE),
        ],
    )
    assert aligned.directional_alignment is MtfAlignment.STRONG_BULLISH
    assert aligned.regime_alignment is MtfAlignment.BULLISH  # 1h range is neutral
