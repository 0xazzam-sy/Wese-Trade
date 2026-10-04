"""Rate of change, ATR-normalized impulse and return acceleration."""

from __future__ import annotations

from collections.abc import Sequence


def roc(closes: Sequence[float], period: int) -> float | None:
    """% change of the last close versus `period` bars earlier."""
    if len(closes) <= period or closes[-1 - period] == 0:
        return None
    return (closes[-1] / closes[-1 - period] - 1.0) * 100.0


def impulse_atr(closes: Sequence[float], period: int, atr: float | None) -> float | None:
    if len(closes) <= period or not atr:
        return None
    return (closes[-1] - closes[-1 - period]) / atr


def acceleration(closes: Sequence[float], period: int) -> float | None:
    """ROC(period) now minus ROC(period) `period` bars ago (positive = speeding up)."""
    if len(closes) <= 2 * period:
        return None
    now = roc(closes, period)
    before = roc(closes[:-period], period)
    if now is None or before is None:
        return None
    return now - before
