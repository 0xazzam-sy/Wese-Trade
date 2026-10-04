"""Multi-timeframe context: the execution timeframe read against higher timeframes.

Higher-timeframe frames use CONFIRMED (closed-candle) analysis only. Alignment rules for
a direction axis (execution direction E, higher-timeframe directions H):
  * no higher timeframe, or none ready          -> unavailable
  * E neutral                                   -> neutral
  * every H == E                                -> strong_bullish / strong_bearish
  * opposite(E) is the H majority (or all of H) -> countertrend
  * H contains both E and opposite(E)           -> mixed
  * otherwise (H agrees or is neutral)          -> bullish / bearish
The same rule is applied to trend direction, swing-structure direction and the
directional regime (strong_up/up = bullish, down = bearish, range/transitional = neutral).
This is context, never a trade signal.
"""

from __future__ import annotations

from app.analysis.config import MTF_CONTEXT
from app.analysis.enums import DirectionalRegime, MtfAlignment
from app.analysis.models import MtfFrame, MultiTimeframeContext
from app.market_data.timeframes import Timeframe

_BULL, _BEAR, _NEUTRAL = "bullish", "bearish", "neutral"


def context_timeframes(timeframe: Timeframe) -> tuple[Timeframe, ...]:
    return MTF_CONTEXT[timeframe]


def _regime_direction(regime: DirectionalRegime | None) -> str | None:
    if regime is None:
        return None
    if regime in (DirectionalRegime.STRONG_UPTREND, DirectionalRegime.UPTREND):
        return _BULL
    if regime in (DirectionalRegime.STRONG_DOWNTREND, DirectionalRegime.DOWNTREND):
        return _BEAR
    return _NEUTRAL


def align(execution: str | None, higher: list[str | None]) -> MtfAlignment:
    ready = [h for h in higher if h is not None]
    if not ready or execution is None:
        return MtfAlignment.UNAVAILABLE
    if execution == _NEUTRAL:
        return MtfAlignment.NEUTRAL
    opposite = _BEAR if execution == _BULL else _BULL
    same = sum(1 for h in ready if h == execution)
    against = sum(1 for h in ready if h == opposite)
    bullish = execution == _BULL
    if same == len(ready):
        return MtfAlignment.STRONG_BULLISH if bullish else MtfAlignment.STRONG_BEARISH
    if against > same or against == len(ready):
        return MtfAlignment.COUNTERTREND
    if against > 0:
        return MtfAlignment.MIXED
    return MtfAlignment.BULLISH if bullish else MtfAlignment.BEARISH


def build_context(execution: MtfFrame, higher: list[MtfFrame]) -> MultiTimeframeContext:
    def val(frame: MtfFrame, attr: str) -> str | None:
        if not frame.ready:
            return None
        value = getattr(frame, attr)
        return value.value if value is not None else None

    ready = [f for f in higher if f.ready]
    vols = [f.volatility_regime for f in [execution, *ready] if f.volatility_regime is not None]
    return MultiTimeframeContext(
        execution=execution,
        higher=tuple(higher),
        directional_alignment=align(val(execution, "trend"), [val(f, "trend") for f in higher]),
        structure_alignment=align(
            val(execution, "structure"), [val(f, "structure") for f in higher]
        ),
        volatility_aligned=(len(set(vols)) == 1) if ready and execution.ready else None,
        regime_alignment=align(
            _regime_direction(execution.directional_regime) if execution.ready else None,
            [_regime_direction(f.directional_regime) if f.ready else None for f in higher],
        ),
    )
