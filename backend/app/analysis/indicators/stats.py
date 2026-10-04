"""Small deterministic statistics helpers (no numpy dependency)."""

from __future__ import annotations

import math
from collections.abc import Sequence


def clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values)


def stdev(values: Sequence[float]) -> float:
    """Population standard deviation."""
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / len(values))


def percentile_rank(window: Sequence[float], value: float) -> float:
    """Percent of `window` below `value` (ties count half). 0-100."""
    if not window:
        return 50.0
    below = sum(1 for v in window if v < value)
    equal = sum(1 for v in window if v == value)
    return 100.0 * (below + 0.5 * equal) / len(window)
