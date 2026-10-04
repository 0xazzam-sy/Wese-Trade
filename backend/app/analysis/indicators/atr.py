"""Average True Range (Wilder smoothing; first value = SMA of the first `period` TRs)."""

from __future__ import annotations


def true_range(high: float, low: float, prev_close: float | None) -> float:
    if prev_close is None:
        return high - low
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


class Atr:
    def __init__(self, period: int) -> None:
        self.period = period
        self.value: float | None = None
        self._prev_close: float | None = None
        self._seed_sum = 0.0
        self._seed_count = 0

    def update(self, high: float, low: float, close: float) -> float | None:
        tr = true_range(high, low, self._prev_close)
        self._prev_close = close
        if self.value is None:
            self._seed_sum += tr
            self._seed_count += 1
            if self._seed_count == self.period:
                self.value = self._seed_sum / self.period
            return self.value
        self.value = (self.value * (self.period - 1) + tr) / self.period
        return self.value
