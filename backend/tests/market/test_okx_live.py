"""Optional live checks against the real OKX PUBLIC API (no credentials).

Skipped by default. Run with:  pytest -m live
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from decimal import Decimal
from itertools import pairwise

import pytest

from app.market_data.models import Candle, LiveQuote, MarketSymbol
from app.market_data.okx.provider import OkxProvider
from app.market_data.okx.rest import OkxRestClient
from app.market_data.okx.stream import OkxSocket
from app.market_data.services.aggregation import aggregate_history
from app.market_data.services.candle_service import now_ms
from app.market_data.timeframes import Timeframe

pytestmark = pytest.mark.live

REST = "https://openapi.okx.com"
PUBLIC_WS = "wss://ws.okx.com/ws/v5/public"
BUSINESS_WS = "wss://ws.okx.com/ws/v5/business"


@pytest.fixture
async def provider() -> AsyncIterator[OkxProvider]:
    p = OkxProvider(
        OkxRestClient(REST), OkxSocket("public", PUBLIC_WS), OkxSocket("business", BUSINESS_WS)
    )
    yield p
    await p.close()


async def symbol(provider: OkxProvider, name: str) -> MarketSymbol:
    return next(s for s in await provider.list_symbols() if s.symbol == name)


async def test_live_instruments(provider: OkxProvider) -> None:
    symbols = {s.symbol: s for s in await provider.list_symbols()}
    assert len(symbols) > 100
    assert all(s.exchange_symbol.endswith("-USDT-SWAP") for s in symbols.values())
    btc = symbols["BTCUSDT"]
    assert btc.exchange_symbol == "BTC-USDT-SWAP"
    assert btc.tick_size > 0
    assert btc.step_size > 0
    assert btc.contract_value_currency == "BTC"
    assert "ETHUSDT" in symbols


def check_candles(candles: list[Candle], timeframe: Timeframe, expected: int) -> None:
    assert len(candles) == expected
    step = timeframe.milliseconds
    opens = [c.open_ms for c in candles]
    assert all(o % step == 0 for o in opens)
    assert all(b - a == step for a, b in pairwise(opens))
    for c in candles:
        assert c.high >= max(c.open, c.close, c.low)
        assert c.low <= min(c.open, c.close)
        assert c.volume >= 0
    assert all(c.is_closed for c in candles[:-1])


@pytest.mark.parametrize(
    "timeframe", [Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.M30, Timeframe.H1]
)
async def test_live_candles(provider: OkxProvider, timeframe: Timeframe) -> None:
    btc = await symbol(provider, "BTCUSDT")
    check_candles(await provider.fetch_candles(btc, timeframe, limit=800), timeframe, 800)


async def test_live_deep_history_crosses_into_history_endpoint(provider: OkxProvider) -> None:
    eth = await symbol(provider, "ETHUSDT")
    check_candles(await provider.fetch_candles(eth, Timeframe.M5, limit=1602), Timeframe.M5, 1602)


async def test_live_10m_from_5m(provider: OkxProvider) -> None:
    btc = await symbol(provider, "BTCUSDT")
    ten = aggregate_history(
        await provider.fetch_candles(btc, Timeframe.M5, limit=200), now_ms=now_ms()
    )
    assert all(c.open_ms % Timeframe.M10.milliseconds == 0 for c in ten)
    assert all(c.is_closed for c in ten[:-1])


async def test_live_tickers_funding_mark_oi_book(provider: OkxProvider) -> None:
    tickers = {t.symbol: t for t in await provider.fetch_tickers()}
    assert tickers["BTCUSDT"].last_price > 0
    funding = {f.symbol: f for f in await provider.fetch_funding()}
    assert funding["BTCUSDT"].next_funding_time is not None
    marks = await provider.fetch_mark_prices()
    assert marks["BTCUSDT"][0] > 0
    btc = await symbol(provider, "BTCUSDT")
    oi = await provider.fetch_open_interest(btc)
    assert oi.contracts is not None
    assert oi.contracts >= Decimal(0)
    book = await provider.fetch_book_ticker(btc)
    assert book is not None
    assert book.ask >= book.bid


async def test_live_business_and_public_sockets(provider: OkxProvider) -> None:
    btc = await symbol(provider, "BTCUSDT")
    candles: list[Candle] = []
    quotes: list[LiveQuote] = []
    states: list[tuple[str, str]] = []

    async def on_candle(candle: Candle) -> None:
        candles.append(candle)

    async def on_quote(quote: LiveQuote) -> None:
        quotes.append(quote)

    async def on_state(feed: str, state: str) -> None:
        states.append((feed, state))

    async def on_reconnected(feed: str) -> None:
        return None

    provider.set_stream_handlers(
        on_candle=on_candle, on_quote=on_quote, on_state=on_state, on_reconnected=on_reconnected
    )
    await provider.subscribe_candles(btc, Timeframe.M1)
    await provider.subscribe_quotes(btc)
    await provider.start()
    async with asyncio.timeout(30):
        while not candles or not any(q.last for q in quotes) or not any(q.mark for q in quotes):
            await asyncio.sleep(0.2)
    assert ("candles", "connected") in states
    assert ("quotes", "connected") in states
    assert candles[0].symbol == "BTCUSDT"
    assert candles[0].open_ms % 60_000 == 0
