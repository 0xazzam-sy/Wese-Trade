"""Exponential moving average, seeded with the SMA of the first `period` values."""

from __future__ import annotations


class Ema:
    def __init__(self, period: int) -> None:
        self.period = period
        self.alpha = 2.0 / (period + 1)
        self.value: float | None = None
        self._seed_sum = 0.0
        self._seed_count = 0

    def update(self, x: float) -> float | None:
        if self.value is None:
            self._seed_sum += x
            self._seed_count += 1
            if self._seed_count == self.period:
                self.value = self._seed_sum / self.period
            return self.value
        self.value = self.alpha * x + (1 - self.alpha) * self.value
        return self.value

    def peek(self, x: float) -> float | None:
        """Value if `x` were the next input (used for the forming candle; no state change)."""
        if self.value is None:
            return None
        return self.alpha * x + (1 - self.alpha) * self.value


def ema_series(values: list[float], period: int) -> list[float | None]:
    ema = Ema(period)
    return [ema.update(v) for v in values]
