"""Bounded, append-only bar buffer with stable absolute indices."""

from __future__ import annotations

from dataclasses import dataclass

from app.market_data.models import Candle


@dataclass(frozen=True, slots=True)
class Bar:
    index: int
    time: int  # open time, epoch seconds
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float

    @property
    def range(self) -> float:
        return self.high - self.low

    @property
    def body(self) -> float:
        return abs(self.close - self.open)

    @property
    def bullish(self) -> bool:
        return self.close > self.open

    @property
    def bearish(self) -> bool:
        return self.close < self.open


def to_bar(candle: Candle, index: int) -> Bar:
    start = candle.open_ms // 1000
    return Bar(
        index=index,
        time=start,
        close_time=start + candle.timeframe.seconds,
        open=float(candle.open),
        high=float(candle.high),
        low=float(candle.low),
        close=float(candle.close),
        volume=float(candle.volume),
    )


class BarSeries:
    """Closed bars only. `bar(i)` uses absolute indices; old bars are trimmed in blocks."""

    def __init__(self, max_bars: int) -> None:
        self._bars: list[Bar] = []
        self._offset = 0
        self._max = max_bars

    def __len__(self) -> int:
        return self._offset + len(self._bars)

    @property
    def first_index(self) -> int:
        return self._offset

    @property
    def last(self) -> Bar:
        return self._bars[-1]

    def append(self, bar: Bar) -> None:
        self._bars.append(bar)
        if len(self._bars) > self._max:
            drop = len(self._bars) - self._max * 3 // 4
            del self._bars[:drop]
            self._offset += drop

    def bar(self, index: int) -> Bar:
        return self._bars[index - self._offset]

    def has(self, index: int) -> bool:
        return self._offset <= index < len(self)

    def window(self, start: int, end: int) -> list[Bar]:
        """Bars with absolute index in [start, end] (clipped to what is kept)."""
        lo = max(start, self._offset) - self._offset
        hi = min(end, len(self) - 1) - self._offset
        return self._bars[lo : hi + 1] if hi >= lo else []

    def tail(self, count: int) -> list[Bar]:
        return self._bars[-count:] if count > 0 else []
