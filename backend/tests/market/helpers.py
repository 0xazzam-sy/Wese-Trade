from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.market_data.models import Candle
from app.market_data.timeframes import Timeframe

BASE = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)  # aligned to 10m
BASE_MS = int(BASE.timestamp() * 1000)
MIN = 60_000


def candle(
    minute_offset: int,
    *,
    tf: Timeframe = Timeframe.M5,
    o: str = "100",
    h: str = "110",
    low: str = "90",
    c: str = "105",
    v: str = "1",
    closed: bool = True,
    symbol: str = "BTCUSDT",
    qv: str | None = None,
) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=tf,
        open_time=datetime.fromtimestamp((BASE_MS + minute_offset * MIN) / 1000, tz=UTC),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
        volume=Decimal(v),
        is_closed=closed,
        quote_volume=Decimal(qv) if qv is not None else None,
    )


def at(minute_offset: float) -> int:
    return int(BASE_MS + minute_offset * MIN)
