"""Market data provider contract. Implementations: later phases (BingX first)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol

from app.market_data.models import Candle, SymbolInfo, Tick
from app.market_data.timeframes import Timeframe


class MarketDataProvider(Protocol):
    """Read-only public market data. There is intentionally no order placement here."""

    name: str

    async def list_symbols(self) -> list[SymbolInfo]: ...

    async def fetch_candles(
        self,
        symbol: str,
        timeframe: Timeframe,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = 500,
    ) -> list[Candle]: ...

    def stream_candles(self, symbol: str, timeframe: Timeframe) -> AsyncIterator[Candle]: ...

    def stream_ticks(self, symbol: str) -> AsyncIterator[Tick]: ...
