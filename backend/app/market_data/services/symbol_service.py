"""Live symbol discovery: no hardcoded pair list. Refreshes periodically from the exchange."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import replace

from app.core.logging import get_logger
from app.market_data.bingx.exceptions import MarketDataError, SymbolUnavailable, UnknownSymbol
from app.market_data.models import MarketSymbol, SymbolStatus
from app.market_data.provider import MarketDataProvider
from app.market_data.services.health import MarketHealth
from app.utils.time import utc_now

logger = get_logger(__name__)

PREFERRED_DEFAULT = "BTCUSDT"
REFRESH_INTERVAL_SECONDS = 20 * 60
RETRY_INTERVAL_SECONDS = 30.0

ChangeCallback = Callable[[set[str]], Awaitable[None]]


class SymbolService:
    def __init__(
        self,
        provider: MarketDataProvider,
        health: MarketHealth,
        *,
        refresh_interval: float = REFRESH_INTERVAL_SECONDS,
        retry_interval: float = RETRY_INTERVAL_SECONDS,
    ) -> None:
        self._provider = provider
        self._health = health
        self._refresh_interval = refresh_interval
        self._retry_interval = retry_interval
        self._symbols: dict[str, MarketSymbol] = {}
        self._task: asyncio.Task[None] | None = None
        self._ready = asyncio.Event()
        self.on_unavailable: ChangeCallback | None = None

    @property
    def loaded(self) -> bool:
        return bool(self._symbols)

    async def refresh(self) -> None:
        fresh = {s.symbol: s for s in await self._provider.list_symbols()}
        previous = self._symbols
        merged = dict(fresh)
        for symbol, old in previous.items():
            if symbol not in fresh:
                # Disappeared from the exchange: keep metadata, mark delisted.
                merged[symbol] = replace(old, status=SymbolStatus.DELISTED, trading_enabled=False)
        became_unavailable = {
            s for s, old in previous.items() if old.is_active and not merged[s].is_active
        }
        self._symbols = merged
        self._health.last_metadata_refresh_at = utc_now()
        self._health.symbol_count = sum(1 for s in merged.values() if s.is_active)
        self._ready.set()
        logger.info(
            "market.symbols_refreshed",
            extra={
                "fields": {
                    "active": self._health.symbol_count,
                    "total": len(merged),
                    "became_unavailable": len(became_unavailable),
                }
            },
        )
        if became_unavailable and self.on_unavailable is not None:
            await self.on_unavailable(became_unavailable)

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="market-symbol-refresh")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.refresh()
                delay = self._refresh_interval
            except MarketDataError as exc:
                logger.warning(
                    "market.symbols_refresh_failed", extra={"fields": {"error": str(exc)}}
                )
                delay = self._retry_interval if not self.loaded else self._refresh_interval / 4
            await asyncio.sleep(delay)

    async def wait_ready(self) -> bool:
        await self._ready.wait()
        return self.loaded

    # --- queries ------------------------------------------------------------
    def get(self, symbol: str) -> MarketSymbol:
        key = symbol.strip().upper().replace("-", "").replace("/", "")
        found = self._symbols.get(key)
        if found is None:
            raise UnknownSymbol(symbol)
        return found

    def require_active(self, symbol: str) -> MarketSymbol:
        found = self.get(symbol)
        if not found.is_active:
            raise SymbolUnavailable(found.symbol)
        return found

    def list(self, *, search: str | None = None, active_only: bool = True) -> list[MarketSymbol]:
        items = [s for s in self._symbols.values() if s.is_active or not active_only]
        if search:
            needle = search.strip().upper().replace("-", "").replace("/", "")
            items = [s for s in items if needle in s.symbol or needle in s.base_asset]
            # Exact/prefix matches first ("BTC" -> BTCUSDT before ...BTC...).
            items.sort(key=lambda s: (not s.base_asset.startswith(needle), len(s.symbol), s.symbol))
        else:
            items.sort(key=lambda s: s.symbol)
        return items

    def default_symbol(self) -> str | None:
        preferred = self._symbols.get(PREFERRED_DEFAULT)
        if preferred is not None and preferred.is_active:
            return preferred.symbol
        active = sorted(s.symbol for s in self._symbols.values() if s.is_active)
        return active[0] if active else None
