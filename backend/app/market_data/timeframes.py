"""Supported analysis timeframes.

Note: BingX perpetual futures do not offer a native 10-minute kline interval. The 10m
timeframe must be aggregated from 5m (or 1m) candles aligned to UTC epoch boundaries.
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
    def is_native_on_bingx(self) -> bool:
        return self is not Timeframe.M10

    @property
    def aggregation_source(self) -> Timeframe | None:
        """Lower timeframe used to build this one when the exchange lacks it."""
        return Timeframe.M5 if self is Timeframe.M10 else None


_SECONDS: dict[Timeframe, int] = {
    Timeframe.M1: 60,
    Timeframe.M5: 300,
    Timeframe.M10: 600,
    Timeframe.M15: 900,
    Timeframe.M30: 1800,
    Timeframe.H1: 3600,
}
