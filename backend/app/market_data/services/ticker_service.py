"""24h tickers, funding and mark prices (one bulk request each), open interest and best
bid/ask (per viewed symbol only), plus a live-quote cache fed by the realtime quotes feed.
All REST data is cached; concurrent callers share one in-flight request."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

from app.market_data.models import (
    BookTicker,
    FundingInfo,
    LiveQuote,
    MarketSymbol,
    OpenInterest,
    Ticker,
)
from app.market_data.provider import MarketDataProvider
from app.market_data.services.cache import TTLCache
from app.utils.time import utc_now

TICKER_TTL = 5.0
FUNDING_TTL = 60.0
MARK_TTL = 10.0
OPEN_INTEREST_TTL = 30.0
BOOK_TTL = 5.0
LIVE_QUOTE_MAX_AGE = timedelta(seconds=10)


class TickerService:
    def __init__(self, provider: MarketDataProvider) -> None:
        self._provider = provider
        self._tickers: TTLCache[str, dict[str, Ticker]] = TTLCache(TICKER_TTL, max_entries=1)
        self._funding: TTLCache[str, dict[str, FundingInfo]] = TTLCache(FUNDING_TTL, max_entries=1)
        self._marks: TTLCache[str, Mapping[str, tuple[Decimal, datetime]]] = TTLCache(
            MARK_TTL, max_entries=1
        )
        self._open_interest: TTLCache[str, OpenInterest] = TTLCache(
            OPEN_INTEREST_TTL, max_entries=64
        )
        self._book: TTLCache[str, BookTicker | None] = TTLCache(BOOK_TTL, max_entries=64)
        self._live: dict[str, LiveQuote] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def _single_flight[T](
        self, key: str, read: Callable[[], T | None], load: Callable[[], Awaitable[T]]
    ) -> T:
        cached = read()
        if cached is not None:
            return cached
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            cached = read()
            if cached is not None:
                return cached
            return await load()

    # --- live quotes (public socket) ------------------------------------------
    def update_live(self, quote: LiveQuote) -> LiveQuote:
        """Merge a partial live update (tickers or mark-price) into the latest quote."""
        current = self._live.get(quote.symbol)
        if current is None:
            merged = quote
        else:
            merged = replace(
                current,
                timestamp=max(current.timestamp, quote.timestamp),
                last=quote.last if quote.last is not None else current.last,
                bid=quote.bid if quote.bid is not None else current.bid,
                ask=quote.ask if quote.ask is not None else current.ask,
                mark=quote.mark if quote.mark is not None else current.mark,
            )
        self._live[quote.symbol] = merged
        return merged

    def live(self, symbol: str) -> LiveQuote | None:
        quote = self._live.get(symbol)
        if quote is None or utc_now() - quote.timestamp > LIVE_QUOTE_MAX_AGE:
            return None
        return quote

    def forget_live(self, symbol: str) -> None:
        self._live.pop(symbol, None)

    # --- bulk REST ------------------------------------------------------------
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

    async def mark_price(self, symbol: str) -> tuple[Decimal, datetime] | None:
        live = self.live(symbol)
        if live is not None and live.mark is not None:
            return live.mark, live.timestamp

        async def load() -> Mapping[str, tuple[Decimal, datetime]]:
            result = await self._provider.fetch_mark_prices()
            self._marks.set("all", result)
            return result

        marks = await self._single_flight("marks", lambda: self._marks.get("all"), load)
        return marks.get(symbol)

    # --- per viewed symbol -----------------------------------------------------
    async def open_interest(self, symbol: MarketSymbol) -> OpenInterest:
        async def load() -> OpenInterest:
            value = await self._provider.fetch_open_interest(symbol)
            self._open_interest.set(symbol.symbol, value)
            return value

        return await self._single_flight(
            f"oi:{symbol.symbol}", lambda: self._open_interest.get(symbol.symbol), load
        )

    async def book(self, symbol: MarketSymbol) -> BookTicker | None:
        live = self.live(symbol.symbol)
        if (
            live is not None
            and live.bid is not None
            and live.ask is not None
            and live.ask >= live.bid
        ):
            return BookTicker(
                symbol=symbol.symbol,
                bid=live.bid,
                bid_qty=None,
                ask=live.ask,
                ask_qty=None,
                timestamp=live.timestamp,
            )
        cached = self._book.get(symbol.symbol)
        if cached is not None:
            return cached
        value = await self._provider.fetch_book_ticker(symbol)
        self._book.set(symbol.symbol, value)
        return value
