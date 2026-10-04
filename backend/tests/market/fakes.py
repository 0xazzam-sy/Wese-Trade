from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.market_data.bingx.exceptions import BingXUnavailable
from app.market_data.bingx.parser import parse_contracts
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
from app.websocket.events import EventEnvelope
from tests.market import fixtures as fx


@dataclass
class FakeStats:
    state: str = "disconnected"
    reconnect_count: int = 0
    last_message_monotonic: float | None = None


class FakeProvider:
    name = "bingx"

    def __init__(self) -> None:
        self.symbols: list[MarketSymbol] = parse_contracts(fx.CONTRACTS)
        self.candles: dict[tuple[str, Timeframe], list[Candle]] = {}
        self.subscribed: list[tuple[str, Timeframe]] = []
        self.calls: list[str] = []
        self.fail_rest = False
        self.stats = FakeStats()
        self.on_candle: CandleCallback | None = None
        self.on_state: StateCallback | None = None
        self.on_reconnected: ReconnectCallback | None = None

    def _guard(self, name: str) -> None:
        self.calls.append(name)
        if self.fail_rest:
            raise BingXUnavailable("down")

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

    async def fetch_open_interest(self, symbol: MarketSymbol) -> OpenInterest:
        raise BingXUnavailable("n/a")

    async def fetch_book_ticker(self, symbol: MarketSymbol) -> BookTicker | None:
        return None

    def set_stream_handlers(
        self,
        *,
        on_candle: CandleCallback,
        on_state: StateCallback,
        on_reconnected: ReconnectCallback,
    ) -> None:
        self.on_candle, self.on_state, self.on_reconnected = on_candle, on_state, on_reconnected

    async def subscribe_candles(self, symbol: MarketSymbol, timeframe: Timeframe) -> None:
        self.subscribed.append((symbol.symbol, timeframe))

    async def unsubscribe_candles(self, symbol: MarketSymbol, timeframe: Timeframe) -> None:
        self.subscribed.remove((symbol.symbol, timeframe))

    @property
    def stream_stats(self) -> FakeStats:
        return self.stats

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    # helpers
    async def push(self, candle: Candle) -> None:
        assert self.on_candle is not None
        await self.on_candle(candle)

    async def set_state(self, state: str) -> None:
        self.stats.state = state
        assert self.on_state is not None
        await self.on_state(state)


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
