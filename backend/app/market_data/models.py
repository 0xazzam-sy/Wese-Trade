"""Normalized, exchange-agnostic market data types.

Rules:
- Prices/quantities are `Decimal` (never binary floats).
- Tick size / precision come from exchange metadata.
- All timestamps are timezone-aware UTC. Candles are keyed by their UTC open time.
- Symbols use the normalized display form (e.g. "BTCUSDT").
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum

from app.market_data.timeframes import Timeframe


class SymbolStatus(StrEnum):
    ACTIVE = "active"
    UNAVAILABLE = "unavailable"  # listed but not tradable/online right now
    DELISTED = "delisted"  # previously seen, no longer returned by the exchange


@dataclass(frozen=True, slots=True)
class MarketSymbol:
    symbol: str  # normalized display form, e.g. "BTCUSDT"
    exchange_symbol: str  # exchange instrument id, e.g. "BTC-USDT-SWAP"
    base_asset: str
    quote_asset: str
    display_name: str  # "BTC/USDT"
    contract_type: str  # "perpetual"
    status: SymbolStatus
    price_precision: int
    quantity_precision: int
    tick_size: Decimal
    step_size: Decimal
    min_quantity: Decimal | None
    min_notional: Decimal | None
    max_leverage: int | None
    trading_enabled: bool
    # Contract specification: sizes (step/min quantity) are in CONTRACTS of this value.
    contract_value: Decimal | None = None
    contract_value_currency: str | None = None

    @property
    def is_active(self) -> bool:
        return self.status is SymbolStatus.ACTIVE


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
    quote_volume: Decimal | None = None
    trade_count: int | None = None

    @property
    def close_time(self) -> datetime:
        """UTC end of the candle (exclusive): open_time + timeframe."""
        return self.open_time + timedelta(seconds=self.timeframe.seconds)

    @property
    def open_ms(self) -> int:
        return int(self.open_time.timestamp() * 1000)

    def closed(self) -> Candle:
        return self if self.is_closed else replace(self, is_closed=True)

    def same_values(self, other: Candle) -> bool:
        return (
            self.open == other.open
            and self.high == other.high
            and self.low == other.low
            and self.close == other.close
            and self.volume == other.volume
            and self.is_closed == other.is_closed
        )


@dataclass(frozen=True, slots=True)
class Tick:
    symbol: str
    timestamp: datetime  # UTC
    price: Decimal


@dataclass(frozen=True, slots=True)
class Ticker:
    symbol: str
    last_price: Decimal
    price_change: Decimal
    price_change_percent: Decimal
    open_price: Decimal | None
    high_24h: Decimal
    low_24h: Decimal
    volume_24h: Decimal
    quote_volume_24h: Decimal | None
    bid: Decimal | None
    ask: Decimal | None
    timestamp: datetime  # UTC


@dataclass(frozen=True, slots=True)
class FundingInfo:
    symbol: str
    funding_rate: Decimal
    mark_price: Decimal | None
    index_price: Decimal | None
    next_funding_time: datetime | None
    timestamp: datetime  # UTC (when fetched)


@dataclass(frozen=True, slots=True)
class OpenInterest:
    """Units differ between exchanges, so every unit the exchange provides is kept explicitly."""

    symbol: str
    contracts: Decimal | None  # number of contracts
    base: Decimal | None  # in the base currency (e.g. BTC)
    usd: Decimal | None  # notional in USD as reported by the exchange
    timestamp: datetime  # UTC


@dataclass(frozen=True, slots=True)
class BookTicker:
    symbol: str
    bid: Decimal
    bid_qty: Decimal | None
    ask: Decimal
    ask_qty: Decimal | None
    timestamp: datetime  # UTC

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


@dataclass(frozen=True, slots=True)
class LiveQuote:
    """Realtime top-of-book / last / mark update. Any field may be absent in one message."""

    symbol: str
    timestamp: datetime  # UTC
    last: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    mark: Decimal | None = None
