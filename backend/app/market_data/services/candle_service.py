"""Candle history + live state per (symbol, native timeframe).

Live finalization: when the provider flags closed candles explicitly (OKX `confirm=1`,
`confirms_closed=True`), that flag is used directly and a closed candle is emitted once and
never reopened. Without such a flag, a live candle is marked closed only when a newer
candle arrives or REST returns it as completed; never on a timer alone.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from app.market_data.models import Candle, MarketSymbol
from app.market_data.provider import MarketDataProvider
from app.market_data.services.aggregation import aggregate_history
from app.market_data.services.cache import TTLCache
from app.market_data.timeframes import Timeframe
from app.utils.time import utc_now

MAX_STORED_CANDLES = 2000
MAX_STREAMS = 256  # v1.2: the live 4.3 scanner alone keeps 90 primary streams + context
PAGED_HISTORY_TTL = 300.0  # `before=` pages contain only closed candles
MAX_HISTORY_LIMIT = 1000


def now_ms() -> int:
    return int(utc_now().timestamp() * 1000)


@dataclass
class LiveResult:
    events: list[Candle]
    gap: bool = False


@dataclass
class CandleStream:
    symbol: str
    timeframe: Timeframe
    closed: dict[int, Candle] = field(default_factory=dict)
    forming: Candle | None = None
    live: bool = False
    stale: bool = False
    last_update: float | None = None  # monotonic seconds
    reconcile_requested_for: int | None = None
    # Closed candles we finalized by inference (a newer candle arrived first). Only these may
    # still be corrected by a later authoritative close; exchange/REST-confirmed ones are final.
    inferred_closed: set[int] = field(default_factory=set)

    @property
    def latest_closed_ms(self) -> int | None:
        return max(self.closed) if self.closed else None

    def _store_closed(self, candle: Candle, *, inferred: bool = False) -> None:
        self.closed[candle.open_ms] = candle
        if inferred:
            self.inferred_closed.add(candle.open_ms)
        else:
            self.inferred_closed.discard(candle.open_ms)
        if len(self.closed) > MAX_STORED_CANDLES:
            for key in sorted(self.closed)[: len(self.closed) - MAX_STORED_CANDLES]:
                del self.closed[key]

    def apply_live(self, candle: Candle, *, trust_close: bool = False) -> LiveResult:
        """Apply one exchange push. Returns the events to publish, oldest first.

        trust_close=True: the exchange flags closed candles explicitly (OKX `confirm`), so a
        closed push finalizes that candle immediately and exactly once. Otherwise pushes are
        never trusted as final and a candle closes only when a newer one arrives.
        A finalized candle is never reopened by a later forming push.
        """
        self.last_update = time.monotonic()
        if not trust_close:
            candle = replace(candle, is_closed=False)
        step = self.timeframe.milliseconds
        latest_closed = self.latest_closed_ms
        forming = self.forming
        stored = self.closed.get(candle.open_ms)

        if stored is not None:
            # Already final. Only an authoritative close may correct a candle we had merely
            # inferred as closed; exchange- or REST-confirmed candles never change again.
            if (
                candle.is_closed
                and candle.open_ms in self.inferred_closed
                and not stored.same_values(candle)
            ):
                self._store_closed(candle)
                return LiveResult([candle])
            if candle.is_closed:  # same values: the inferred close is now confirmed
                self.inferred_closed.discard(candle.open_ms)
            return LiveResult([])

        if candle.is_closed:
            self._store_closed(candle)
            events: list[Candle] = []
            if forming is not None and forming.open_ms < candle.open_ms:
                # Missed the older candle's close: finalize it from its last state.
                final = forming.closed()
                self._store_closed(final, inferred=True)
                events.append(final)
            if forming is not None and forming.open_ms <= candle.open_ms:
                self.forming = None
            events.append(candle)
            # Gap: the closed candle starts after the next candle we expected to see.
            if forming is not None:
                expected: int | None = forming.open_ms + step
            else:
                expected = latest_closed + step if latest_closed is not None else None
            gap = expected is not None and candle.open_ms > expected
            return LiveResult(events, gap=gap)

        if forming is None:
            if latest_closed is not None and candle.open_ms <= latest_closed:
                return LiveResult([])  # late update for a finalized candle
            self.forming = candle
            gap = latest_closed is not None and candle.open_ms > latest_closed + step
            return LiveResult([candle], gap=gap)

        if candle.open_ms == forming.open_ms:
            if forming.same_values(candle):
                return LiveResult([])
            self.forming = candle
            return LiveResult([candle])

        if candle.open_ms > forming.open_ms:
            final = forming.closed()
            self._store_closed(final, inferred=True)
            self.forming = candle
            gap = candle.open_ms > forming.open_ms + step
            return LiveResult([final, candle], gap=gap)

        return LiveResult([])  # older than the forming candle: ignore (REST owns history)

    def merge_rest(self, candles: list[Candle]) -> list[Candle]:
        """Reconcile with authoritative REST data. Returns candles that changed/appeared."""
        changed: list[Candle] = []
        for candle in candles:
            if candle.is_closed:
                existing = self.closed.get(candle.open_ms)
                if existing is None or not existing.same_values(candle):
                    self._store_closed(candle)
                    changed.append(candle)
                if self.forming is not None and self.forming.open_ms <= candle.open_ms:
                    self.forming = None
            elif self.forming is None or self.forming.open_ms < candle.open_ms:
                self.forming = candle
                changed.append(candle)
        # A forming candle older than the newest closed one is obsolete.
        latest = self.latest_closed_ms
        if self.forming is not None and latest is not None and self.forming.open_ms <= latest:
            self.forming = None
        return sorted(changed, key=lambda c: c.open_ms)

    def has_coverage(self, limit: int, at_ms: int) -> bool:
        """True if a forming candle exists and the last `limit - 1` closed buckets are stored."""
        step = self.timeframe.milliseconds
        last_closed = self.timeframe.bucket_start_ms(at_ms) - step
        if self.forming is None or self.forming.open_ms < last_closed:
            return False
        needed = max(limit - 1, 0)
        return all((last_closed - i * step) in self.closed for i in range(needed))

    def history(self, limit: int) -> list[Candle]:
        closed = [self.closed[k] for k in sorted(self.closed)]
        if self.forming is not None:
            closed = [c for c in closed if c.open_ms < self.forming.open_ms]
            return [*closed[-(limit - 1) :], self.forming] if limit > 1 else [self.forming]
        return closed[-limit:]

    def recent_source(self, since_ms: int) -> list[Candle]:
        items = [c for k, c in self.closed.items() if k >= since_ms]
        if self.forming is not None and self.forming.open_ms >= since_ms:
            items.append(self.forming)
        return sorted(items, key=lambda c: c.open_ms)


class CandleService:
    def __init__(self, provider: MarketDataProvider) -> None:
        self._provider = provider
        self._streams: OrderedDict[tuple[str, Timeframe], CandleStream] = OrderedDict()
        self._pages: TTLCache[tuple[str, Timeframe, int, int], list[Candle]] = TTLCache(
            PAGED_HISTORY_TTL, max_entries=128
        )

    def stream(self, symbol: str, timeframe: Timeframe) -> CandleStream:
        key = (symbol, timeframe)
        found = self._streams.get(key)
        if found is None:
            found = CandleStream(symbol, timeframe)
            self._streams[key] = found
            self._evict(keep=key)
        self._streams.move_to_end(key)
        return found

    def existing(self, symbol: str, timeframe: Timeframe) -> CandleStream | None:
        return self._streams.get((symbol, timeframe))

    def _evict(self, keep: tuple[str, Timeframe] | None = None) -> None:
        """Drop the oldest idle streams above the cap; never the one being requested."""
        while len(self._streams) > MAX_STREAMS:
            for key, stream in self._streams.items():
                if key != keep and not stream.live:
                    del self._streams[key]
                    break
            else:
                return

    async def history(
        self,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        *,
        limit: int,
        before: datetime | None = None,
    ) -> list[Candle]:
        limit = max(1, min(limit, MAX_HISTORY_LIMIT))
        if timeframe.is_synthetic:
            source_limit = limit * 2 + 2
            source = await self._native_history(symbol, timeframe.source, source_limit, before)
            return aggregate_history(source, now_ms=now_ms())[-limit:]
        return await self._native_history(symbol, timeframe, limit, before)

    async def _native_history(
        self, symbol: MarketSymbol, timeframe: Timeframe, limit: int, before: datetime | None
    ) -> list[Candle]:
        if before is not None:
            end = before - timedelta(milliseconds=1)
            key = (symbol.symbol, timeframe, int(end.timestamp() * 1000), limit)
            cached = self._pages.get(key)
            if cached is None:
                fetched = await self._provider.fetch_candles(
                    symbol, timeframe, limit=limit, end_time=end
                )
                cached = [c for c in fetched if c.is_closed]
                self._pages.set(key, cached)
            return cached

        stream = self.stream(symbol.symbol, timeframe)
        if stream.live and not stream.stale and stream.has_coverage(limit, now_ms()):
            return stream.history(limit)
        fetched = await self._provider.fetch_candles(symbol, timeframe, limit=limit)
        stream.merge_rest(fetched)
        return stream.history(limit)

    async def reconcile(
        self, symbol: MarketSymbol, timeframe: Timeframe, *, limit: int = 30
    ) -> list[Candle]:
        """Fetch recent REST candles and merge them; returns changed candles."""
        fetched = await self._provider.fetch_candles(symbol, timeframe, limit=limit)
        return self.stream(symbol.symbol, timeframe).merge_rest(fetched)
