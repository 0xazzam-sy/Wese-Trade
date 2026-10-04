"""Market data API schemas. Decimals serialize as strings (no precision loss)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import field_serializer

from app.market_data.models import BookTicker, FundingInfo, MarketSymbol, OpenInterest, Ticker
from app.schemas.common import ApiModel


class DecimalModel(ApiModel):
    @field_serializer("*", when_used="json")
    def _decimal_as_plain_string(self, value: Any) -> Any:
        return format(value, "f") if isinstance(value, Decimal) else value


class SymbolOut(DecimalModel):
    symbol: str
    base_asset: str
    quote_asset: str
    display_name: str
    contract_type: str
    status: str
    price_precision: int
    quantity_precision: int
    tick_size: Decimal
    step_size: Decimal
    min_quantity: Decimal | None
    min_notional: Decimal | None
    max_leverage: int | None
    trading_enabled: bool
    contract_value: Decimal | None
    contract_value_currency: str | None

    @classmethod
    def of(cls, s: MarketSymbol) -> SymbolOut:
        return cls(
            symbol=s.symbol,
            base_asset=s.base_asset,
            quote_asset=s.quote_asset,
            display_name=s.display_name,
            contract_type=s.contract_type,
            status=s.status.value,
            price_precision=s.price_precision,
            quantity_precision=s.quantity_precision,
            tick_size=s.tick_size,
            step_size=s.step_size,
            min_quantity=s.min_quantity,
            min_notional=s.min_notional,
            max_leverage=s.max_leverage,
            trading_enabled=s.trading_enabled,
            contract_value=s.contract_value,
            contract_value_currency=s.contract_value_currency,
        )


class SymbolList(ApiModel):
    items: list[SymbolOut]
    total: int
    default_symbol: str | None
    refreshed_at: datetime | None


class TickerOut(DecimalModel):
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
    timestamp: datetime

    @classmethod
    def of(cls, t: Ticker) -> TickerOut:
        return cls(**{name: getattr(t, name) for name in cls.model_fields})


class TickerList(ApiModel):
    items: list[TickerOut]
    fetched_at: datetime


class CandleOut(DecimalModel):
    time: int  # UTC epoch seconds of the candle open
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    is_closed: bool


class CandleList(ApiModel):
    symbol: str
    timeframe: str
    candles: list[CandleOut]


class FundingOut(DecimalModel):
    funding_rate: Decimal
    mark_price: Decimal | None
    index_price: Decimal | None
    next_funding_time: datetime | None
    timestamp: datetime

    @classmethod
    def of(cls, f: FundingInfo) -> FundingOut:
        return cls(**{name: getattr(f, name) for name in cls.model_fields})


class OpenInterestOut(DecimalModel):
    """Every unit the exchange reports, explicitly (never mixed)."""

    contracts: Decimal | None
    base: Decimal | None
    usd: Decimal | None
    timestamp: datetime

    @classmethod
    def of(cls, o: OpenInterest) -> OpenInterestOut:
        return cls(contracts=o.contracts, base=o.base, usd=o.usd, timestamp=o.timestamp)


class BookOut(DecimalModel):
    bid: Decimal
    bid_qty: Decimal | None
    ask: Decimal
    ask_qty: Decimal | None
    spread: Decimal
    timestamp: datetime

    @classmethod
    def of(cls, b: BookTicker) -> BookOut:
        return cls(
            bid=b.bid,
            bid_qty=b.bid_qty,
            ask=b.ask,
            ask_qty=b.ask_qty,
            spread=b.spread,
            timestamp=b.timestamp,
        )


class SymbolDetails(ApiModel):
    symbol: SymbolOut
    ticker: TickerOut | None
    funding: FundingOut | None
    open_interest: OpenInterestOut | None
    book: BookOut | None
