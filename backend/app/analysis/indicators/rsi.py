"""Relative Strength Index (Wilder). A feature only: never a buy/sell rule."""

from __future__ import annotations


class Rsi:
    def __init__(self, period: int) -> None:
        self.period = period
        self.value: float | None = None
        self._prev: float | None = None
        self._avg_gain = 0.0
        self._avg_loss = 0.0
        self._count = 0

    @staticmethod
    def _rsi(gain: float, loss: float) -> float:
        if loss == 0:
            return 100.0 if gain > 0 else 50.0
        return 100.0 - 100.0 / (1.0 + gain / loss)

    def update(self, close: float) -> float | None:
        if self._prev is None:
            self._prev = close
            return None
        change = close - self._prev
        self._prev = close
        gain, loss = max(change, 0.0), max(-change, 0.0)
        self._count += 1
        if self._count <= self.period:
            self._avg_gain += gain / self.period
            self._avg_loss += loss / self.period
            if self._count < self.period:
                return None
        else:
            self._avg_gain = (self._avg_gain * (self.period - 1) + gain) / self.period
            self._avg_loss = (self._avg_loss * (self.period - 1) + loss) / self.period
        self.value = self._rsi(self._avg_gain, self._avg_loss)
        return self.value

    def peek(self, close: float) -> float | None:
        """RSI if `close` were the next close (forming candle; no state change)."""
        if self.value is None or self._prev is None:
            return None
        change = close - self._prev
        gain, loss = max(change, 0.0), max(-change, 0.0)
        g = (self._avg_gain * (self.period - 1) + gain) / self.period
        lo = (self._avg_loss * (self.period - 1) + loss) / self.period
        return self._rsi(g, lo)
