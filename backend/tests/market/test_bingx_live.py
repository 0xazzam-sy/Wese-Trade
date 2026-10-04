"""Optional live checks against the real BingX public API (no credentials).

Skipped by default. Run with:  pytest -m live
"""

from __future__ import annotations

import asyncio
import itertools
from decimal import Decimal

import pytest

from app.market_data.bingx.provider import BingXProvider
from app.market_data.bingx.rest import BingXRestClient
from app.market_data.bingx.stream import BingXMarketStream
from app.market_data.models import Candle
from app.market_data.services.aggregation import aggregate_history
from app.market_data.services.candle_service import now_ms
from app.market_data.timeframes import Timeframe

pytestmark = pytest.mark.live

REST = "https://open-api.bingx.com"
WS = "wss://open-api-swap.bingx.com/swap-market"


@pytest.fixture
async def provider() -> BingXProvider:
    return BingXProvider(BingXRestClient(REST), BingXMarketStream(WS))


async def test_live_contracts_include_btc(provider: BingXProvider) -> None:
    symbols = {s.symbol: s for s in await provider.list_symbols()}
    assert len(symbols) > 50
    btc = symbols["BTCUSDT"]
    assert btc.exchange_symbol == "BTC-USDT"
    assert btc.tick_size > 0
    await provider.close()


@pytest.mark.parametrize(
    "timeframe", [Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.M30, Timeframe.H1]
)
async def test_live_klines_are_aligned_and_contiguous(
    provider: BingXProvider, timeframe: Timeframe
) -> None:
    btc = next(s for s in await provider.list_symbols() if s.symbol == "BTCUSDT")
    candles = await provider.fetch_candles(btc, timeframe, limit=500)
    assert len(candles) == 500
    step = timeframe.milliseconds
    assert all(c.open_ms % step == 0 for c in candles)
    assert all(b.open_ms - a.open_ms == step for a, b in itertools.pairwise(candles))
    assert candles[-1].is_closed is False or candles[-1].open_ms + step <= now_ms()
    await provider.close()


async def test_live_10m_from_5m(provider: BingXProvider) -> None:
    btc = next(s for s in await provider.list_symbols() if s.symbol == "BTCUSDT")
    ten = aggregate_history(
        await provider.fetch_candles(btc, Timeframe.M5, limit=200), now_ms=now_ms()
    )
    assert all(c.open_ms % Timeframe.M10.milliseconds == 0 for c in ten)
    assert all(c.is_closed for c in ten[:-1])
    await provider.close()


async def test_live_tickers_funding_oi_book(provider: BingXProvider) -> None:
    tickers = {t.symbol: t for t in await provider.fetch_tickers()}
    assert tickers["BTCUSDT"].last_price > 0
    funding = {f.symbol: f for f in await provider.fetch_funding()}
    assert "BTCUSDT" in funding
    btc = next(s for s in await provider.list_symbols() if s.symbol == "BTCUSDT")
    assert (await provider.fetch_open_interest(btc)).value >= Decimal(0)
    book = await provider.fetch_book_ticker(btc)
    assert book is not None
    assert book.ask >= book.bid
    await provider.close()


async def test_live_websocket_kline_stream(provider: BingXProvider) -> None:
    btc = next(s for s in await provider.list_symbols() if s.symbol == "BTCUSDT")
    received: list[Candle] = []
    states: list[str] = []

    async def on_candle(candle: Candle) -> None:
        received.append(candle)

    async def on_state(state: str) -> None:
        states.append(state)

    async def on_reconnected() -> None:
        return None

    provider.set_stream_handlers(
        on_candle=on_candle, on_state=on_state, on_reconnected=on_reconnected
    )
    await provider.subscribe_candles(btc, Timeframe.M1)
    await provider.start()
    async with asyncio.timeout(30):
        while not received:
            await asyncio.sleep(0.2)
    assert "connected" in states
    assert received[0].symbol == "BTCUSDT"
    assert received[0].open_ms % 60_000 == 0
    await provider.close()
