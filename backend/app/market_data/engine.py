"""MarketDataEngine: the single owner of live market state.

    provider (OKX) -> normalization -> services (symbols, tickers, candles, 10m) ->
    cache / live state -> Publisher (app WebSocket) + REST routes

Nothing here knows about FastAPI or exchange wire formats.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable, Coroutine, Iterable
from typing import Any, Protocol

from app.core.logging import get_logger
from app.market_data.exceptions import MarketDataError
from app.market_data.models import Candle, LiveQuote, MarketSymbol
from app.market_data.provider import FEED_CANDLES, FEED_QUOTES, MarketDataProvider
from app.market_data.services.aggregation import LiveAggregator
from app.market_data.services.candle_service import CandleService, now_ms
from app.market_data.services.events import candle_event, dec
from app.market_data.services.health import MarketHealth
from app.market_data.services.subscription_manager import (
    AppKey,
    NativeKey,
    SubscriptionChange,
    SubscriptionManager,
)
from app.market_data.services.symbol_service import SymbolService
from app.market_data.services.ticker_service import TickerService
from app.market_data.timeframes import Timeframe
from app.utils.time import utc_isoformat, utc_now
from app.websocket.events import EventEnvelope, EventType

logger = get_logger(__name__)

STALE_AFTER_SECONDS = 60.0
MONITOR_INTERVAL_SECONDS = 5.0
CLOSE_GRACE_MS = 10_000  # after a bucket ends, wait this long before asking REST to finalize
TICK_REPEAT_SECONDS = 1.0
RECOVERY_LIMIT = 60


class Publisher(Protocol):
    def send_to(self, consumers: Iterable[str], envelope: EventEnvelope) -> None: ...

    def broadcast(self, envelope: EventEnvelope) -> None: ...


CandleListener = Callable[[Candle], None]
ResyncListener = Callable[[AppKey], None]


class MarketDataEngine:
    def __init__(
        self,
        provider: MarketDataProvider,
        publisher: Publisher,
        *,
        health: MarketHealth | None = None,
        stale_after: float = STALE_AFTER_SECONDS,
        monitor_interval: float = MONITOR_INTERVAL_SECONDS,
    ) -> None:
        self.provider = provider
        self.publisher = publisher
        self.health = health or MarketHealth(provider=provider.name)
        self.symbols = SymbolService(provider, self.health)
        self.tickers = TickerService(provider)
        self.candles = CandleService(provider)
        self.subscriptions = SubscriptionManager()
        self._aggregators: dict[str, LiveAggregator] = {}
        self._last_tick: dict[str, tuple[str, float]] = {}
        self._last_quote: dict[str, float] = {}  # symbol -> monotonic time of last quote
        self._stale_after = stale_after
        self._monitor_interval = monitor_interval
        self._tasks: set[asyncio.Task[Any]] = set()
        self._monitor: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._last_status: str | None = None
        self.health.on_change = self._broadcast_status_if_changed
        # In-process observers (the analysis engine): every published candle (native and
        # aggregated 10m) and every history resync. Listener errors never break the feed.
        self.candle_listeners: list[CandleListener] = []
        self.resync_listeners: list[ResyncListener] = []

    # --- lifecycle ------------------------------------------------------------
    async def start(self) -> None:
        self.provider.set_stream_handlers(
            on_candle=self._on_candle,
            on_quote=self._on_quote,
            on_state=self._on_state,
            on_reconnected=self._on_reconnected,
        )
        self.symbols.on_unavailable = self._on_symbols_unavailable
        await self.provider.start()
        self.symbols.start()
        self._monitor = asyncio.create_task(self._monitor_loop(), name="market-monitor")
        logger.info("market.engine_started", extra={"fields": {"provider": self.provider.name}})

    async def stop(self) -> None:
        await self.symbols.stop()
        if self._monitor is not None:
            self._monitor.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._monitor
        for task in list(self._tasks):
            task.cancel()
        await self.provider.close()

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # --- consumer subscriptions -----------------------------------------------
    async def subscribe(self, consumer: str, symbol: str, timeframe: Timeframe) -> MarketSymbol:
        """Raises UnknownSymbol / SymbolUnavailable. Idempotent per consumer."""
        market = self.symbols.require_active(symbol)
        async with self._lock:
            before = self.subscriptions.symbols
            change = self.subscriptions.acquire(consumer, (market.symbol, timeframe))
            await self._apply(change)
            await self._sync_quotes(before)
        self.publisher.send_to([consumer], self._stream_state_event((market.symbol, timeframe)))
        return market

    async def unsubscribe(self, consumer: str, symbol: str, timeframe: Timeframe) -> None:
        key = (symbol.strip().upper(), timeframe)
        async with self._lock:
            before = self.subscriptions.symbols
            await self._apply(self.subscriptions.release(consumer, key))
            await self._sync_quotes(before)

    async def release_all(self, consumer: str) -> None:
        async with self._lock:
            before = self.subscriptions.symbols
            for change in self.subscriptions.release_all(consumer):
                await self._apply(change)
            await self._sync_quotes(before)

    async def _sync_quotes(self, before: set[str]) -> None:
        """One quotes subscription (last/bid/ask/mark) per symbol with any chart on it."""
        after = self.subscriptions.symbols
        for symbol in sorted(after - before):
            await self.provider.subscribe_quotes(self.symbols.get(symbol))
        for symbol in sorted(before - after):
            self.tickers.forget_live(symbol)
            with contextlib.suppress(MarketDataError):
                await self.provider.unsubscribe_quotes(self.symbols.get(symbol))

    async def _apply(self, change: SubscriptionChange) -> None:
        if change.native_added is not None:
            symbol, timeframe = change.native_added
            stream = self.candles.stream(symbol, timeframe)
            stream.live, stream.stale = True, False
            stream.last_update = time.monotonic()  # grace period before staleness
            stream.reconcile_requested_for = None
            await self.provider.subscribe_candles(self.symbols.get(symbol), timeframe)
            logger.info(
                "market.stream_opened", extra={"fields": {"stream": _label(change.native_added)}}
            )
        if change.app_key_added is not None and change.app_key_added[1].is_synthetic:
            await self._ensure_aggregator(change.app_key_added[0])
        if change.app_key_removed is not None:
            symbol, timeframe = change.app_key_removed
            if timeframe.is_synthetic and (symbol, timeframe) not in self.subscriptions.app_keys:
                self._aggregators.pop(symbol, None)
        if change.native_removed is not None:
            symbol, timeframe = change.native_removed
            stream = self.candles.stream(symbol, timeframe)
            stream.live, stream.stale, stream.forming = False, False, None
            with contextlib.suppress(MarketDataError):
                await self.provider.unsubscribe_candles(self.symbols.get(symbol), timeframe)
            logger.info(
                "market.stream_closed", extra={"fields": {"stream": _label(change.native_removed)}}
            )
        self.health.active_streams = [_label(k) for k in self.subscriptions.native_keys]

    async def _ensure_aggregator(self, symbol: str) -> None:
        """Seed the live 10m bucket with 5m children already known (from REST if needed)."""
        aggregator = LiveAggregator(symbol)
        stream = self.candles.stream(symbol, Timeframe.M5)
        bucket = Timeframe.M10.bucket_start_ms(now_ms())
        if not stream.recent_source(bucket):
            with contextlib.suppress(MarketDataError):
                await self.candles.reconcile(self.symbols.get(symbol), Timeframe.M5, limit=3)
        aggregator.seed(stream.recent_source(bucket), now_ms=now_ms())
        self._aggregators[symbol] = aggregator

    # --- provider callbacks -----------------------------------------------------
    async def _on_candle(self, candle: Candle) -> None:
        stream = self.candles.existing(candle.symbol, candle.timeframe)
        if stream is None or not stream.live:
            return  # late push for a stream we already released
        self.health.last_candle_message_at = utc_now()
        if stream.stale:
            stream.stale = False
            self._refresh_stale_list()
            logger.info(
                "market.stream_recovered",
                extra={"fields": {"stream": _label((candle.symbol, candle.timeframe))}},
            )
            # Notify every app key fed by this native stream (e.g. 10m charts on a 5m stream).
            for key in self.subscriptions.app_keys_for_native((candle.symbol, candle.timeframe)):
                self._publish_stream_state(key)
        result = stream.apply_live(candle, trust_close=self.provider.confirms_closed)
        self._publish_candles(result.events)
        if result.events and self.health.quote_feed_state != "connected":
            # Fallback price source while the quotes feed is down.
            last = result.events[-1]
            self._maybe_tick(last.symbol, last.close)
        if result.gap:
            logger.warning(
                "market.gap_detected",
                extra={"fields": {"stream": _label((candle.symbol, candle.timeframe))}},
            )
            self._spawn(self._recover((candle.symbol, candle.timeframe), reason="gap"))

    def _publish_candles(self, candles: list[Candle]) -> None:
        for candle in candles:
            key = (candle.symbol, candle.timeframe)
            consumers = self.subscriptions.consumers_of(key)
            if consumers:
                self.publisher.send_to(
                    consumers, EventEnvelope.of(EventType.MARKET_CANDLE, candle_event(candle))
                )
            self._notify_candle(candle)
            aggregator = self._aggregators.get(candle.symbol)
            if candle.timeframe is Timeframe.M5 and aggregator is not None:
                derived = aggregator.update(candle, now_ms=now_ms())
                ten = self.subscriptions.consumers_of((candle.symbol, Timeframe.M10))
                for item in derived:
                    self.publisher.send_to(
                        ten, EventEnvelope.of(EventType.MARKET_CANDLE, candle_event(item))
                    )
                    self._notify_candle(item)

    def _notify_candle(self, candle: Candle) -> None:
        for listener in self.candle_listeners:
            try:
                listener(candle)
            except Exception:
                logger.exception("market.candle_listener_failed")

    def _notify_resync(self, key: AppKey) -> None:
        for listener in self.resync_listeners:
            try:
                listener(key)
            except Exception:
                logger.exception("market.resync_listener_failed")

    async def _on_quote(self, quote: LiveQuote) -> None:
        if quote.symbol not in self.subscriptions.symbols:
            return  # late push for a released symbol
        self.health.last_quote_message_at = utc_now()
        self._last_quote[quote.symbol] = time.monotonic()
        self.tickers.update_live(quote)
        if quote.last is not None:
            self._maybe_tick(quote.symbol, quote.last)

    def _maybe_tick(self, symbol: str, price: Any) -> None:
        text = dec(price) or ""
        now = time.monotonic()
        last = self._last_tick.get(symbol)
        if last is not None and last[0] == text and now - last[1] < TICK_REPEAT_SECONDS:
            return
        self._last_tick[symbol] = (text, now)
        consumers = self.subscriptions.consumers_of_symbol(symbol)
        if consumers:
            payload = {"symbol": symbol, "price": text, "timestamp": utc_isoformat(utc_now())}
            self.publisher.send_to(consumers, EventEnvelope.of(EventType.MARKET_TICK, payload))

    async def _on_state(self, feed: str, state: str) -> None:
        self.health.reconnect_count = sum(f.reconnect_count for f in self.provider.feeds.values())
        if feed == FEED_QUOTES:
            self.health.quote_feed_state = state
            self._broadcast_status_if_changed()
            return
        previous = self.health.candle_feed_state
        self.health.candle_feed_state = state
        self._broadcast_status_if_changed()
        if previous == "connected" and state != "connected":
            for key in self.subscriptions.app_keys:
                self._publish_stream_state(key)

    async def _on_reconnected(self, feed: str) -> None:
        self.health.reconnect_count = sum(f.reconnect_count for f in self.provider.feeds.values())
        if feed != FEED_CANDLES:
            return  # quotes resubscribe with a fresh snapshot; nothing to reconcile
        natives = sorted(self.subscriptions.native_keys)
        logger.info("market.gap_recovery_started", extra={"fields": {"streams": len(natives)}})
        self.health.gap_recovery_in_progress = True
        try:
            for native in natives:
                await self._recover(native, reason="reconnect")
        finally:
            self.health.gap_recovery_in_progress = False

    async def _recover(self, native: NativeKey, *, reason: str) -> None:
        """Reconcile recent candles from REST, then tell clients to resync."""
        symbol, timeframe = native
        try:
            changed = await self.candles.reconcile(
                self.symbols.get(symbol), timeframe, limit=RECOVERY_LIMIT
            )
        except MarketDataError as exc:
            logger.warning(
                "market.gap_recovery_failed",
                extra={"fields": {"stream": _label(native), "error": str(exc)}},
            )
            return
        stream = self.candles.stream(symbol, timeframe)
        stream.last_update = time.monotonic()
        if timeframe is Timeframe.M5 and symbol in self._aggregators:
            bucket = Timeframe.M10.bucket_start_ms(now_ms())
            self._aggregators[symbol].seed(stream.recent_source(bucket), now_ms=now_ms())
        self.health.gap_recoveries += 1
        logger.info(
            "market.gap_recovered",
            extra={"fields": {"stream": _label(native), "reason": reason, "changed": len(changed)}},
        )
        for key in self.subscriptions.app_keys_for_native(native):
            consumers = self.subscriptions.consumers_of(key)
            payload = {"symbol": key[0], "timeframe": key[1].value, "reason": reason}
            self.publisher.send_to(consumers, EventEnvelope.of(EventType.MARKET_RESYNC, payload))
            self.publisher.send_to(consumers, self._stream_state_event(key))
            self._notify_resync(key)

    async def _on_symbols_unavailable(self, symbols: set[str]) -> None:
        async with self._lock:
            for key in [k for k in self.subscriptions.app_keys if k[0] in symbols]:
                consumers = self.subscriptions.consumers_of(key)
                payload = {"symbol": key[0], "timeframe": key[1].value, "state": "unavailable"}
                self.publisher.send_to(
                    consumers, EventEnvelope.of(EventType.MARKET_STREAM, payload)
                )
                for consumer in consumers:
                    await self._apply(self.subscriptions.release(consumer, key))
        logger.warning("market.symbols_unavailable", extra={"fields": {"symbols": sorted(symbols)}})

    # --- monitoring -------------------------------------------------------------
    async def _monitor_loop(self) -> None:
        while True:
            await asyncio.sleep(self._monitor_interval)
            try:
                self.check_streams()
            except Exception:
                logger.exception("market.monitor_failed")

    def check_streams(self) -> None:
        """Mark silent streams STALE and ask REST to finalize candles whose bucket ended.

        A candle stream is stale when it has been silent for `stale_after` while its symbol
        is visibly trading (quotes arrived meanwhile), or for 3x `stale_after` regardless.
        A merely quiet instrument (no quotes either) is not treated as a broken feed.
        """
        if self.health.candle_feed_state != "connected":
            return
        now_mono, current_ms = time.monotonic(), now_ms()
        for native in self.subscriptions.native_keys:
            stream = self.candles.stream(*native)
            silent = now_mono - stream.last_update if stream.last_update is not None else 0.0
            last_quote = self._last_quote.get(native[0])
            trading = last_quote is not None and now_mono - last_quote < self._stale_after
            if not stream.stale and (
                (silent > self._stale_after and trading) or silent > 3 * self._stale_after
            ):
                stream.stale = True
                logger.warning("market.stream_stale", extra={"fields": {"stream": _label(native)}})
                for key in self.subscriptions.app_keys_for_native(native):
                    self._publish_stream_state(key)
            forming = stream.forming
            if (
                forming is not None
                and forming.open_ms + forming.timeframe.milliseconds + CLOSE_GRACE_MS < current_ms
                and stream.reconcile_requested_for != forming.open_ms
            ):
                stream.reconcile_requested_for = forming.open_ms
                self._spawn(self._finalize_via_rest(native))
        self._refresh_stale_list()

    async def _finalize_via_rest(self, native: NativeKey) -> None:
        symbol, timeframe = native
        try:
            changed = await self.candles.reconcile(self.symbols.get(symbol), timeframe, limit=3)
        except MarketDataError:
            return
        self._publish_candles(changed)

    def _refresh_stale_list(self) -> None:
        self.health.stale_streams = [
            _label(k) for k in self.subscriptions.native_keys if self.candles.stream(*k).stale
        ]
        self._broadcast_status_if_changed()

    def _broadcast_status_if_changed(self) -> None:
        """Broadcast market.status whenever the overall state changes, whatever the cause
        (exchange socket, REST reachability or stale streams)."""
        overall = self.health.overall
        if overall != self._last_status:
            self._last_status = overall
            self.publisher.broadcast(self.status_event())

    # --- status payloads ----------------------------------------------------------
    def stream_state(self, key: AppKey) -> str:
        if self.health.candle_feed_state != "connected":
            return "reconnecting"
        stream = self.candles.existing(key[0], key[1].source)
        if stream is not None and stream.stale:
            return "stale"
        return "live"

    def _stream_state_event(self, key: AppKey) -> EventEnvelope:
        return EventEnvelope.of(
            EventType.MARKET_STREAM,
            {"symbol": key[0], "timeframe": key[1].value, "state": self.stream_state(key)},
        )

    def _publish_stream_state(self, key: AppKey) -> None:
        self.publisher.send_to(self.subscriptions.consumers_of(key), self._stream_state_event(key))

    def status_event(self) -> EventEnvelope:
        return EventEnvelope.of(
            EventType.MARKET_STATUS,
            {
                "provider": self.provider.name,
                "state": self.health.overall,
                "rest_reachable": self.health.rest_reachable,
            },
        )

    def health_snapshot(self) -> dict[str, Any]:
        snapshot = self.health.snapshot()
        feeds: dict[str, Any] = {}
        for name, stats in self.provider.feeds.items():
            age = (
                round(time.monotonic() - stats.last_message_monotonic, 1)
                if stats.last_message_monotonic is not None
                else None
            )
            feeds[name] = {
                "state": stats.state,
                "reconnect_count": stats.reconnect_count,
                "seconds_since_last_message": age,
            }
        snapshot["feeds"] = feeds
        snapshot["reconnect_count"] = sum(f["reconnect_count"] for f in feeds.values())
        return snapshot


def _label(key: tuple[str, Timeframe]) -> str:
    return f"{key[0]}:{key[1].value}"
