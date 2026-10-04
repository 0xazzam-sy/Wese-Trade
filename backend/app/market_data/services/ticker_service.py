"""24h tickers (one bulk request), funding (one bulk request), open interest and best
bid/ask (per *viewed* symbol only). All cached; concurrent callers share one request."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.market_data.models import BookTicker, FundingInfo, MarketSymbol, OpenInterest, Ticker
from app.market_data.provider import MarketDataProvider
from app.market_data.services.cache import TTLCache

TICKER_TTL = 5.0
FUNDING_TTL = 60.0
OPEN_INTEREST_TTL = 30.0
BOOK_TTL = 5.0


class TickerService:
    def __init__(self, provider: MarketDataProvider) -> None:
        self._provider = provider
        self._tickers: TTLCache[str, dict[str, Ticker]] = TTLCache(TICKER_TTL, max_entries=1)
        self._funding: TTLCache[str, dict[str, FundingInfo]] = TTLCache(FUNDING_TTL, max_entries=1)
        self._open_interest: TTLCache[str, OpenInterest] = TTLCache(
            OPEN_INTEREST_TTL, max_entries=64
        )
        self._book: TTLCache[str, BookTicker | None] = TTLCache(BOOK_TTL, max_entries=64)
        self._locks: dict[str, asyncio.Lock] = {}

    async def _single_flight[T](
        self, key: str, read: Callable[[], T | None], load: Callable[[], Awaitable[T]]
    ) -> T:
        cached = read()
        if cached is not None:
            return cached
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = read()  # another caller may have filled it while we waited
            if cached is not None:
                return cached
            return await load()

    async def tickers(self) -> dict[str, Ticker]:
        async def load() -> dict[str, Ticker]:
            result = {t.symbol: t for t in await self._provider.fetch_tickers()}
            self._tickers.set("all", result)
            return result

        return await self._single_flight("tickers", lambda: self._tickers.get("all"), load)

    async def funding(self) -> dict[str, FundingInfo]:
        async def load() -> dict[str, FundingInfo]:
            result = {f.symbol: f for f in await self._provider.fetch_funding()}
            self._funding.set("all", result)
            return result

        return await self._single_flight("funding", lambda: self._funding.get("all"), load)

    async def open_interest(self, symbol: MarketSymbol) -> OpenInterest:
        async def load() -> OpenInterest:
            value = await self._provider.fetch_open_interest(symbol)
            self._open_interest.set(symbol.symbol, value)
            return value

        return await self._single_flight(
            f"oi:{symbol.symbol}", lambda: self._open_interest.get(symbol.symbol), load
        )

    async def book(self, symbol: MarketSymbol) -> BookTicker | None:
        cached = self._book.get(symbol.symbol)
        if cached is not None:
            return cached
        value = await self._provider.fetch_book_ticker(symbol)
        self._book.set(symbol.symbol, value)
        return value
