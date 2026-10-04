"""Market data provider contract. OKX is the implementation (public data only).

Read-only. There is intentionally no order placement, account or private API anywhere.
A provider exposes two realtime FEEDS:
- "candles": kline updates (drives charts, gap recovery and stale detection)
- "quotes":  last / bid / ask / mark updates (drives price headers and details)
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from app.market_data.models import (
    BookTicker,
    Candle,
    FundingInfo,
    LiveQuote,
    MarketSymbol,
    OpenInterest,
    Ticker,
)
from app.market_data.timeframes import Timeframe

FEED_CANDLES = "candles"
FEED_QUOTES = "quotes"

CandleCallback = Callable[[Candle], Awaitable[None]]
QuoteCallback = Callable[[LiveQuote], Awaitable[None]]
StateCallback = Callable[[str, str], Awaitable[None]]  # (feed, state)
ReconnectCallback = Callable[[str], Awaitable[None]]  # (feed)


class FeedStats(Protocol):
    """Read-only view of one realtime connection, for health reporting."""

    state: str
    reconnect_count: int
    last_message_monotonic: float | None


class MarketDataProvider(Protocol):
    name: str
    # True when the exchange flags closed candles explicitly (no time-based guessing).
    confirms_closed: bool

    # --- REST (request/response) ---------------------------------------------
    async def list_symbols(self) -> list[MarketSymbol]: ...

    async def fetch_candles(
        self,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        *,
        limit: int,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        """Native timeframes only. Oldest-first; the newest may be forming."""
        ...

    async def fetch_tickers(self) -> list[Ticker]: ...

    async def fetch_funding(self) -> list[FundingInfo]: ...

    async def fetch_mark_prices(self) -> Mapping[str, tuple[Decimal, datetime]]: ...

    async def fetch_open_interest(self, symbol: MarketSymbol) -> OpenInterest: ...

    async def fetch_book_ticker(self, symbol: MarketSymbol) -> BookTicker | None: ...

    # --- Streaming -----------------------------------------------------------
    def set_stream_handlers(
        self,
        *,
        on_candle: CandleCallback,
        on_quote: QuoteCallback,
        on_state: StateCallback,
        on_reconnected: ReconnectCallback,
    ) -> None: ...

    async def subscribe_candles(self, symbol: MarketSymbol, timeframe: Timeframe) -> None: ...

    async def unsubscribe_candles(self, symbol: MarketSymbol, timeframe: Timeframe) -> None: ...

    async def subscribe_quotes(self, symbol: MarketSymbol) -> None: ...

    async def unsubscribe_quotes(self, symbol: MarketSymbol) -> None: ...

    @property
    def feeds(self) -> Mapping[str, FeedStats]: ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...
