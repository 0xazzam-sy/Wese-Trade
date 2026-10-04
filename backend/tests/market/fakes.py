from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from app.market_data.exceptions import ProviderUnavailable
from app.market_data.models import (
    BookTicker,
    Candle,
    FundingInfo,
    LiveQuote,
    MarketSymbol,
    OpenInterest,
    Ticker,
)
from app.market_data.okx.parser import parse_instruments
from app.market_data.provider import (
    FEED_CANDLES,
    FEED_QUOTES,
    CandleCallback,
    QuoteCallback,
    ReconnectCallback,
    StateCallback,
)
from app.market_data.timeframes import Timeframe
from app.websocket.events import EventEnvelope
from tests.market import fixtures as fx


@dataclass
class FakeStats:
    state: str = "disconnected"
    reconnect_count: int = 0
    last_message_monotonic: float | None = None


class FakeProvider:
    name = "okx"

    def __init__(self, *, confirms_closed: bool = True) -> None:
        self.confirms_closed = confirms_closed
        self.symbols: list[MarketSymbol] = parse_instruments(fx.INSTRUMENTS)
        self.candles: dict[tuple[str, Timeframe], list[Candle]] = {}
        self.subscribed: list[tuple[str, Timeframe]] = []
        self.quotes: list[str] = []
        self.calls: list[str] = []
        self.fail_rest = False
        self.stats = {FEED_CANDLES: FakeStats(), FEED_QUOTES: FakeStats()}
        self.on_candle: CandleCallback | None = None
        self.on_quote: QuoteCallback | None = None
        self.on_state: StateCallback | None = None
        self.on_reconnected: ReconnectCallback | None = None

    def _guard(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_rest:
            raise ProviderUnavailable("down")

    async def list_symbols(self) -> list[MarketSymbol]:
        self._guard("symbols")
        return list(self.symbols)

    async def fetch_candles(
        self,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        *,
        limit: int,
        end_time: datetime | None = None,
    ) -> list[Candle]:
        self._guard(f"candles:{symbol.symbol}:{timeframe.value}:{limit}")
        items = self.candles.get((symbol.symbol, timeframe), [])
        if end_time is not None:
            items = [c for c in items if c.open_time <= end_time]
        return items[-limit:]

    async def fetch_tickers(self) -> list[Ticker]:
        self._guard("tickers")
        return []

    async def fetch_funding(self) -> list[FundingInfo]:
        self._guard("funding")
        return []

    async def fetch_mark_prices(self) -> Mapping[str, tuple[Decimal, datetime]]:
        self._guard("marks")
        return {}

    async def fetch_open_interest(self, symbol: MarketSymbol) -> OpenInterest:
        raise ProviderUnavailable("n/a")

    async def fetch_book_ticker(self, symbol: MarketSymbol) -> BookTicker | None:
        return None

    def set_stream_handlers(
        self,
        *,
        on_candle: CandleCallback,
        on_quote: QuoteCallback,
        on_state: StateCallback,
        on_reconnected: ReconnectCallback,
    ) -> None:
        self.on_candle, self.on_quote = on_candle, on_quote
        self.on_state, self.on_reconnected = on_state, on_reconnected

    async def subscribe_candles(self, symbol: MarketSymbol, timeframe: Timeframe) -> None:
        self.subscribed.append((symbol.symbol, timeframe))

    async def unsubscribe_candles(self, symbol: MarketSymbol, timeframe: Timeframe) -> None:
        self.subscribed.remove((symbol.symbol, timeframe))

    async def subscribe_quotes(self, symbol: MarketSymbol) -> None:
        self.quotes.append(symbol.symbol)

    async def unsubscribe_quotes(self, symbol: MarketSymbol) -> None:
        self.quotes.remove(symbol.symbol)

    @property
    def feeds(self) -> Mapping[str, FakeStats]:
        return self.stats

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    # helpers
    async def push(self, candle: Candle) -> None:
        assert self.on_candle is not None
        await self.on_candle(candle)

    async def push_quote(self, quote: LiveQuote) -> None:
        assert self.on_quote is not None
        await self.on_quote(quote)

    async def set_state(self, state: str, feed: str = FEED_CANDLES) -> None:
        self.stats[feed].state = state
        assert self.on_state is not None
        await self.on_state(feed, state)

    async def reconnected(self, feed: str = FEED_CANDLES) -> None:
        self.stats[feed].reconnect_count += 1
        assert self.on_reconnected is not None
        await self.on_reconnected(feed)


@dataclass
class FakePublisher:
    sent: list[tuple[frozenset[str], EventEnvelope]] = field(default_factory=list)
    broadcasts: list[EventEnvelope] = field(default_factory=list)

    def send_to(self, consumers: Iterable[str], envelope: EventEnvelope) -> None:
        targets = frozenset(consumers)
        if targets:
            self.sent.append((targets, envelope))

    def broadcast(self, envelope: EventEnvelope) -> None:
        self.broadcasts.append(envelope)

    def of_type(self, event_type: str, consumer: str | None = None) -> list[dict[str, Any]]:
        return [
            env.data
            for targets, env in self.sent
            if env.type == event_type and (consumer is None or consumer in targets)
        ]

    def clear(self) -> None:
        self.sent.clear()
        self.broadcasts.clear()
