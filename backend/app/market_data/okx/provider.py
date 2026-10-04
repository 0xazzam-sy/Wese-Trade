"""OKX implementation of `MarketDataProvider` (public REST + two shared WebSockets).

business socket (/ws/v5/business): candle channels  -> "candles" feed
public socket   (/ws/v5/public):   tickers, mark-price -> "quotes" feed
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.core.logging import get_logger
from app.market_data.models import (
    BookTicker,
    Candle,
    FundingInfo,
    MarketSymbol,
    OpenInterest,
    Ticker,
)
from app.market_data.okx import constants as c
from app.market_data.okx.parser import (
    parse_book,
    parse_candle_push,
    parse_candles,
    parse_funding,
    parse_instruments,
    parse_mark_prices,
    parse_open_interest,
    parse_quote_push,
    parse_tickers,
)
from app.market_data.okx.rest import OkxRestClient
from app.market_data.okx.stream import OkxSocket
from app.market_data.provider import (
    FEED_CANDLES,
    FEED_QUOTES,
    CandleCallback,
    FeedStats,
    QuoteCallback,
    ReconnectCallback,
    StateCallback,
)
from app.market_data.timeframes import Timeframe
from app.utils.time import utc_now

logger = get_logger(__name__)


def candle_channel(timeframe: Timeframe) -> str:
    return f"candle{c.BARS[timeframe]}"


class OkxProvider:
    name = "okx"
    confirms_closed = True

    def __init__(self, rest: OkxRestClient, public: OkxSocket, business: OkxSocket) -> None:
        self.rest = rest
        self.public = public
        self.business = business
        self._on_candle: CandleCallback | None = None
        self._on_quote: QuoteCallback | None = None

    # --- REST -------------------------------------------------------------------
    async def list_symbols(self) -> list[MarketSymbol]:
        return parse_instruments(await self.rest.get(c.PATH_INSTRUMENTS, {"instType": c.INST_TYPE}))

    async def fetch_candles(
        self,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        *,
        limit: int,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        """Pages backwards with `after` (records strictly older than ts). /market/candles
        reaches the most recent 1440 rows; older pages come from /market/history-candles."""
        if timeframe not in c.BARS:
            raise ValueError(f"{timeframe} is not a native OKX bar")
        collected: dict[int, Candle] = {}
        after = int(end_time.timestamp() * 1000) + 1 if end_time is not None else None
        path = c.PATH_CANDLES
        while len(collected) < limit:
            params: dict[str, str | int] = {
                "instId": symbol.exchange_symbol,
                "bar": c.BARS[timeframe],
                "limit": c.CANDLES_PAGE_LIMIT,
            }
            if after is not None:
                params["after"] = after
            rows: Any = await self.rest.get(path, params)
            candles = parse_candles(rows, symbol.symbol, timeframe)
            if not candles:
                if path == c.PATH_CANDLES:
                    path = c.PATH_HISTORY_CANDLES  # recent window exhausted: continue older
                    continue
                break
            new = [k for k in candles if k.open_ms not in collected]
            for candle in candles:
                existing = collected.get(candle.open_ms)
                if existing is None or candle.is_closed:
                    collected[candle.open_ms] = candle
            if not new:
                break
            after = candles[0].open_ms
        ordered = [collected[k] for k in sorted(collected)]
        return ordered[-limit:]

    async def fetch_tickers(self) -> list[Ticker]:
        return parse_tickers(await self.rest.get(c.PATH_TICKERS, {"instType": c.INST_TYPE}))

    async def fetch_funding(self) -> list[FundingInfo]:
        # instId=ANY is documented: one request returns every perpetual's funding info.
        return parse_funding(
            await self.rest.get(c.PATH_FUNDING_RATE, {"instId": "ANY"}), now=utc_now()
        )

    async def fetch_mark_prices(self) -> Mapping[str, tuple[Decimal, datetime]]:
        return parse_mark_prices(await self.rest.get(c.PATH_MARK_PRICE, {"instType": c.INST_TYPE}))

    async def fetch_open_interest(self, symbol: MarketSymbol) -> OpenInterest:
        data = await self.rest.get(
            c.PATH_OPEN_INTEREST, {"instType": c.INST_TYPE, "instId": symbol.exchange_symbol}
        )
        return parse_open_interest(data, symbol.symbol)

    async def fetch_book_ticker(self, symbol: MarketSymbol) -> BookTicker | None:
        data = await self.rest.get(c.PATH_TICKER, {"instId": symbol.exchange_symbol})
        rows = data if isinstance(data, list) else []
        return parse_book(rows[0]) if rows else None

    # --- streaming ----------------------------------------------------------------
    def set_stream_handlers(
        self,
        *,
        on_candle: CandleCallback,
        on_quote: QuoteCallback,
        on_state: StateCallback,
        on_reconnected: ReconnectCallback,
    ) -> None:
        self._on_candle = on_candle
        self._on_quote = on_quote

        async def business_state(state: str) -> None:
            await on_state(FEED_CANDLES, state)

        async def public_state(state: str) -> None:
            await on_state(FEED_QUOTES, state)

        async def business_reconnected() -> None:
            await on_reconnected(FEED_CANDLES)

        async def public_reconnected() -> None:
            await on_reconnected(FEED_QUOTES)

        self.business.set_handlers(
            on_message=self._handle_candles,
            on_state=business_state,
            on_reconnected=business_reconnected,
        )
        self.public.set_handlers(
            on_message=self._handle_quotes, on_state=public_state, on_reconnected=public_reconnected
        )

    async def _handle_candles(self, message: Mapping[str, Any]) -> None:
        if self._on_candle is None:
            return
        for candle in parse_candle_push(message):
            await self._on_candle(candle)

    async def _handle_quotes(self, message: Mapping[str, Any]) -> None:
        if self._on_quote is None:
            return
        for quote in parse_quote_push(message):
            await self._on_quote(quote)

    async def subscribe_candles(self, symbol: MarketSymbol, timeframe: Timeframe) -> None:
        self.business.subscribe(candle_channel(timeframe), symbol.exchange_symbol)

    async def unsubscribe_candles(self, symbol: MarketSymbol, timeframe: Timeframe) -> None:
        self.business.unsubscribe(candle_channel(timeframe), symbol.exchange_symbol)

    async def subscribe_quotes(self, symbol: MarketSymbol) -> None:
        self.public.subscribe(c.CHANNEL_TICKERS, symbol.exchange_symbol)
        self.public.subscribe(c.CHANNEL_MARK_PRICE, symbol.exchange_symbol)

    async def unsubscribe_quotes(self, symbol: MarketSymbol) -> None:
        self.public.unsubscribe(c.CHANNEL_TICKERS, symbol.exchange_symbol)
        self.public.unsubscribe(c.CHANNEL_MARK_PRICE, symbol.exchange_symbol)

    @property
    def feeds(self) -> Mapping[str, FeedStats]:
        return {FEED_CANDLES: self.business, FEED_QUOTES: self.public}

    async def start(self) -> None:
        self.business.start()
        self.public.start()

    async def close(self) -> None:
        await self.business.close()
        await self.public.close()
        await self.rest.close()
