"""Canonical analysis timeframes, owned by the backend.

The exchange (OKX) has no native 10-minute candle. `10m` is synthetic: it is
aggregated from 5m candles bucketed on UTC epoch boundaries (see services/aggregation.py).
The frontend never needs to know which timeframes are native.
"""

from __future__ import annotations

from enum import StrEnum


class Timeframe(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M10 = "10m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"

    @property
    def seconds(self) -> int:
        return _SECONDS[self]

    @property
    def milliseconds(self) -> int:
        return _SECONDS[self] * 1000

    @property
    def is_synthetic(self) -> bool:
        return self is Timeframe.M10

    @property
    def source(self) -> Timeframe:
        """Native timeframe whose exchange stream feeds this one (itself if native)."""
        return Timeframe.M5 if self is Timeframe.M10 else self

    @property
    def aggregation_source(self) -> Timeframe | None:
        """Lower timeframe used to build this one when the exchange lacks it."""
        return Timeframe.M5 if self is Timeframe.M10 else None

    def bucket_start_ms(self, timestamp_ms: int) -> int:
        """Floor a UTC epoch-millisecond timestamp to this timeframe's bucket start."""
        size = self.milliseconds
        return timestamp_ms - (timestamp_ms % size)


_SECONDS: dict[Timeframe, int] = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M10: 600,
    Timeframe.M15: 900,
    Timeframe.M30: 1800,
    Timeframe.H1: 3600,
}
