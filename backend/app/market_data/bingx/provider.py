"""BingX implementation of `MarketDataProvider` (REST + one shared market WebSocket)."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from app.core.logging import get_logger
from app.market_data.bingx import constants as c
from app.market_data.bingx.exceptions import BingXApiError
from app.market_data.bingx.parser import (
    parse_book_from_depth,
    parse_contracts,
    parse_funding,
    parse_kline_push,
    parse_klines,
    parse_open_interest,
    parse_tickers,
)
from app.market_data.bingx.rest import BingXRestClient
from app.market_data.bingx.stream import BingXMarketStream
from app.market_data.models import (
    BookTicker,
    Candle,
    FundingInfo,
    MarketSymbol,
    OpenInterest,
    Ticker,
)
from app.market_data.provider import CandleCallback, ReconnectCallback, StateCallback
from app.market_data.timeframes import Timeframe
from app.utils.time import utc_now

logger = get_logger(__name__)


def _now_ms() -> int:
    return int(utc_now().timestamp() * 1000)


def kline_data_type(symbol: MarketSymbol, timeframe: Timeframe) -> str:
    return f"{symbol.exchange_symbol}@kline_{c.INTERVALS[timeframe]}"


class BingXProvider:
    name = "bingx"

    def __init__(self, rest: BingXRestClient, stream: BingXMarketStream) -> None:
        self.rest = rest
        self.stream = stream
        self._klines_path = c.PATH_KLINES_V3
        self._on_candle: CandleCallback | None = None

    # --- REST ---------------------------------------------------------------
    async def list_symbols(self) -> list[MarketSymbol]:
        return parse_contracts(await self.rest.get(c.PATH_CONTRACTS))

    async def _klines(self, params: Mapping[str, str | int]) -> Any:
        try:
            return await self.rest.get(self._klines_path, params)
        except BingXApiError as exc:
            # v3 is the current path; fall back to the documented v2 path if v3 is absent.
            if exc.code == 404 and self._klines_path == c.PATH_KLINES_V3:
                logger.warning("bingx.klines_v3_unavailable_fallback_v2")
                self._klines_path = c.PATH_KLINES_V2
                return await self.rest.get(self._klines_path, params)
            raise

    async def fetch_candles(
        self,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        *,
        limit: int,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        if timeframe not in c.INTERVALS:
            raise ValueError(f"{timeframe} is not a native BingX interval")
        remaining = limit
        end_ms = int(end_time.timestamp() * 1000) if end_time else None
        collected: dict[int, Candle] = {}
        while remaining > 0:
            batch = min(remaining, c.KLINE_MAX_LIMIT)
            params: dict[str, str | int] = {
                "symbol": symbol.exchange_symbol,
                "interval": c.INTERVALS[timeframe],
                "limit": batch,
            }
            if end_ms is not None:
                params["endTime"] = end_ms
            candles = parse_klines(
                await self._klines(params), symbol.symbol, timeframe, now_ms=_now_ms()
            )
            if not candles:
                break
            new = [k for k in candles if k.open_ms not in collected]
            for candle in candles:
                collected[candle.open_ms] = candle
            remaining -= len(new)
            if len(candles) < batch or not new:
                break
            end_ms = candles[0].open_ms - 1  # page backwards
        ordered = [collected[k] for k in sorted(collected)]
        return ordered[-limit:]

    async def fetch_tickers(self) -> list[Ticker]:
        return parse_tickers(await self.rest.get(c.PATH_TICKER), now=utc_now())

    async def fetch_funding(self) -> list[FundingInfo]:
        return parse_funding(await self.rest.get(c.PATH_PREMIUM_INDEX), now=utc_now())

    async def fetch_open_interest(self, symbol: MarketSymbol) -> OpenInterest:
        data = await self.rest.get(c.PATH_OPEN_INTEREST, {"symbol": symbol.exchange_symbol})
        return parse_open_interest(data, symbol.symbol, now=utc_now())

    async def fetch_book_ticker(self, symbol: MarketSymbol) -> BookTicker | None:
        data = await self.rest.get(c.PATH_DEPTH, {"symbol": symbol.exchange_symbol, "limit": 5})
        return parse_book_from_depth(data, symbol.symbol, now=utc_now())

    # --- streaming ----------------------------------------------------------
    def set_stream_handlers(
        self,
        *,
        on_candle: CandleCallback,
        on_state: StateCallback,
        on_reconnected: ReconnectCallback,
    ) -> None:
        self._on_candle = on_candle
        self.stream.set_handlers(
            on_message=self._handle_message, on_state=on_state, on_reconnected=on_reconnected
        )

    async def _handle_message(self, message: Mapping[str, Any]) -> None:
        if self._on_candle is None:
            return
        for candle in parse_kline_push(message, now_ms=_now_ms()):
            await self._on_candle(candle)

    async def subscribe_candles(self, symbol: MarketSymbol, timeframe: Timeframe) -> None:
        await self.stream.subscribe(kline_data_type(symbol, timeframe))

    async def unsubscribe_candles(self, symbol: MarketSymbol, timeframe: Timeframe) -> None:
        await self.stream.unsubscribe(kline_data_type(symbol, timeframe))

    @property
    def stream_stats(self) -> BingXMarketStream:
        return self.stream

    async def start(self) -> None:
        self.stream.start()

    async def close(self) -> None:
        await self.stream.close()
        await self.rest.close()
