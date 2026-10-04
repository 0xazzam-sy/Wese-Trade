"""Serialization of market data into app WebSocket / REST payloads.

Decimals are sent as plain strings (no exponent) so the browser never loses precision in
transport; candle times are UTC epoch seconds (the chart's native unit).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.market_data.models import Candle
from app.utils.time import utc_isoformat


def dec(value: Decimal | None) -> str | None:
    if value is None:
        return None
    text = format(value, "f")
    return text


def candle_payload(candle: Candle) -> dict[str, Any]:
    return {
        "time": candle.open_ms // 1000,
        "open": dec(candle.open),
        "high": dec(candle.high),
        "low": dec(candle.low),
        "close": dec(candle.close),
        "volume": dec(candle.volume),
        "is_closed": candle.is_closed,
    }


def candle_event(candle: Candle) -> dict[str, Any]:
    return {
        "symbol": candle.symbol,
        "timeframe": candle.timeframe.value,
        "candle": candle_payload(candle),
        "close_time": utc_isoformat(candle.close_time),
    }
