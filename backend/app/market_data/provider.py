"""Market data provider contract. BingX is the first (and in phase 2 only) implementation.

Read-only public market data. There is intentionally no order placement anywhere.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Protocol

from app.market_data.models import (
    BookTicker,
    Candle,
    FundingInfo,
    MarketSymbol,
    OpenInterest,
    Ticker,
)
from app.market_data.timeframes import Timeframe

CandleCallback = Callable[[Candle], Awaitable[None]]
StateCallback = Callable[[str], Awaitable[None]]
ReconnectCallback = Callable[[], Awaitable[None]]


class MarketDataProvider(Protocol):
    name: str

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
        """Native timeframes only. Returns candles oldest-first; the newest may be forming."""
        ...

    async def fetch_tickers(self) -> list[Ticker]: ...

    async def fetch_funding(self) -> list[FundingInfo]: ...

    async def fetch_open_interest(self, symbol: MarketSymbol) -> OpenInterest: ...

    async def fetch_book_ticker(self, symbol: MarketSymbol) -> BookTicker | None: ...

    # --- Streaming -----------------------------------------------------------
    def set_stream_handlers(
        self,
        *,
        on_candle: CandleCallback,
        on_state: StateCallback,
        on_reconnected: ReconnectCallback,
    ) -> None: ...

    async def subscribe_candles(self, symbol: MarketSymbol, timeframe: Timeframe) -> None: ...

    async def unsubscribe_candles(self, symbol: MarketSymbol, timeframe: Timeframe) -> None: ...

    @property
    def stream_stats(self) -> StreamStats: ...

    async def start(self) -> None: ...

    async def close(self) -> None: ...


class StreamStats(Protocol):
    """Read-only view of the provider's realtime connection, for health reporting."""

    state: str
    reconnect_count: int
    last_message_monotonic: float | None
