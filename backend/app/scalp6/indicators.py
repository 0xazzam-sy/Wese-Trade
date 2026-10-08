"""Incremental indicators for the scalp-6 engine (closed candles only)."""

from __future__ import annotations

from bisect import bisect_left, insort
from collections import deque


class Ema:
    __slots__ = ("hist", "k", "value")

    def __init__(self, n: int, keep: int = 6) -> None:
        self.k = 2 / (n + 1)
        self.value: float | None = None
        self.hist: deque[float] = deque(maxlen=keep)

    def update(self, x: float) -> float:
        self.value = x if self.value is None else self.value + self.k * (x - self.value)
        self.hist.append(self.value)
        return self.value

    def slope(self) -> float:
        """Change over the kept window (oldest -> newest)."""
        return self.hist[-1] - self.hist[0] if len(self.hist) > 1 else 0.0


class Atr:
    __slots__ = ("n", "prev_close", "value")

    def __init__(self, n: int = 14) -> None:
        self.n = n
        self.value: float | None = None
        self.prev_close: float | None = None

    def update(self, h: float, lo: float, c: float) -> float:
        tr = h - lo
        if self.prev_close is not None:
            tr = max(tr, abs(h - self.prev_close), abs(lo - self.prev_close))
        self.value = tr if self.value is None else self.value + (tr - self.value) / self.n
        self.prev_close = c
        return self.value


class Rsi:
    __slots__ = ("gain", "hist", "loss", "n", "prev", "value")

    def __init__(self, n: int = 14) -> None:
        self.n = n
        self.gain = self.loss = 0.0
        self.prev: float | None = None
        self.value = 50.0
        self.hist: deque[float] = deque(maxlen=4)

    def update(self, c: float) -> float:
        if self.prev is not None:
            d = c - self.prev
            self.gain += (max(d, 0.0) - self.gain) / self.n
            self.loss += (max(-d, 0.0) - self.loss) / self.n
            self.value = 100.0 if self.loss == 0 else 100 - 100 / (1 + self.gain / self.loss)
        self.prev = c
        self.hist.append(self.value)
        return self.value

    def slope(self) -> float:
        return self.hist[-1] - self.hist[0] if len(self.hist) > 1 else 0.0


class RollingPercentile:
    """Percentile rank (0..100) of the newest value within a trailing window."""

    __slots__ = ("sorted", "window")

    def __init__(self, size: int) -> None:
        self.window: deque[float] = deque(maxlen=size)
        self.sorted: list[float] = []

    def update(self, x: float) -> float:
        if len(self.window) == self.window.maxlen:
            self.sorted.pop(bisect_left(self.sorted, self.window[0]))
        self.window.append(x)
        insort(self.sorted, x)
        return 100 * bisect_left(self.sorted, x) / max(1, len(self.sorted) - 1)


class RollingMean:
    __slots__ = ("total", "window")

    def __init__(self, size: int) -> None:
        self.window: deque[float] = deque(maxlen=size)
        self.total = 0.0

    def update(self, x: float) -> float:
        if len(self.window) == self.window.maxlen:
            self.total -= self.window[0]
        self.window.append(x)
        self.total += x
        return self.total / len(self.window)

    @property
    def mean(self) -> float:
        return self.total / len(self.window) if self.window else 0.0
