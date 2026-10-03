"""Normalized market data types.

Prices and quantities are `Decimal` — never binary floats — and precision/tick size come
from exchange metadata (`SymbolInfo`), not from hardcoded assumptions.
All timestamps are timezone-aware UTC; candles are keyed by their open time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.market_data.timeframes import Timeframe


@dataclass(frozen=True, slots=True)
class SymbolInfo:
    symbol: str  # normalized display form, e.g. "BTCUSDT"
    exchange_symbol: str  # exchange-native form, e.g. "BTC-USDT"
    base_asset: str
    quote_asset: str
    tick_size: Decimal
    step_size: Decimal
    price_precision: int
    quantity_precision: int
    is_trading: bool


@dataclass(frozen=True, slots=True)
class Candle:
    symbol: str
    timeframe: Timeframe
    open_time: datetime  # UTC, inclusive
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    is_closed: bool  # False while the candle is still forming


@dataclass(frozen=True, slots=True)
class Tick:
    symbol: str
    timestamp: datetime  # UTC
    price: Decimal
