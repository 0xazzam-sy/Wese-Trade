"""Live analysis: keeps one MarketAnalyzer per (symbol, timeframe) in sync with the feed.

    MarketDataEngine --(candle listener)--> AnalysisService --> `analysis.update` (WS)
                     --(resync listener)-->                 --> latest snapshot (REST)

* Seeding: an analyzer is built from `ANALYSIS_LOOKBACK` candles of history, then fed
  every CLOSED candle in order (incremental: one step per candle, never a full re-run).
  Closed candles arriving while seeding are buffered and applied afterwards.
* Integrity: a gap, an out-of-order candle, a corrected closed candle, or an engine
  history resync triggers a re-seed. The analyzer never skips or reorders candles.
* Traffic: a FULL snapshot is sent on subscribe and on every candle close (structural
  events are only confirmed at a close). While a candle forms, a small LIVE payload is
  sent at most every `LIVE_INTERVAL` seconds, or within `LIVE_MIN_INTERVAL` when a
  developing structural feature appears/disappears. Raw ticks never trigger analysis.
* Multi-timeframe: higher-timeframe context streams are subscribed internally (consumer
  `INTERNAL_CONSUMER`) and analyzed with confirmed candles only.
* Cache: latest snapshots live in memory only (persistence can be added for replay).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.analysis.config import DEFAULT_CONFIG, AnalysisConfig
from app.analysis.engine import AnalysisOrderError, MarketAnalyzer
from app.analysis.models import AnalysisSnapshot, MtfFrame
from app.analysis.multi_timeframe.context import context_timeframes
from app.analysis.serialize import snapshot_payload, to_payload
from app.core.logging import get_logger
from app.market_data.engine import MarketDataEngine
from app.market_data.exceptions import MarketDataError
from app.market_data.models import Candle
from app.market_data.services.subscription_manager import AppKey
from app.market_data.timeframes import Timeframe
from app.websocket.events import EventEnvelope, EventType

logger = get_logger(__name__)

INTERNAL_CONSUMER = "analysis-engine"
ANALYSIS_LOOKBACK = 1000
LIVE_INTERVAL = 4.0
LIVE_MIN_INTERVAL = 1.0
LOOP_INTERVAL = 0.5
SEED_RETRY_SECONDS = (2.0, 5.0, 15.0, 30.0)
ON_DEMAND_TTL = 30.0
HISTORY_MAX_ROWS = 300
RECENT_CLOSED = 8

# Fields of the snapshot that can change while a candle is forming.
LIVE_FIELDS = (
    "symbol",
    "timeframe",
    "analysis_ready",
    "candle_time",
    "forming_time",
    "price",
    "generated_at",
    "forming_candle",
    "developing",
    "premium_discount",
    "ote",
)


class AnalysisListener(Protocol):
    """In-process observer (the signal service). Called synchronously; must not block."""

    def on_seeded(self, key: AppKey, analyzer: MarketAnalyzer) -> None: ...

    def on_closed(self, key: AppKey, analyzer: MarketAnalyzer) -> None: ...

    def on_forming(self, key: AppKey) -> None: ...


def not_ready_frame(timeframe: Timeframe) -> MtfFrame:
    return MtfFrame(timeframe.value, False, None, None, None, None, None)


def live_payload(full: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "live", **{k: full.get(k) for k in LIVE_FIELDS}}


def developing_signature(snapshot: AnalysisSnapshot) -> tuple[Any, ...]:
    dev = snapshot.developing
    if dev is None:
        return ()
    return (
        tuple(p.id for p in (*dev.swing_pivots, *dev.internal_pivots)),
        tuple((b.layer, b.type, b.direction) for b in (*dev.swing_breaks, *dev.internal_breaks)),
        tuple(s.pool_id for s in dev.sweeps),
        tuple(g.id for g in dev.fair_value_gaps),
    )


@dataclass
class _Entry:
    key: AppKey
    analyzer: MarketAnalyzer | None = None
    state: str = "seeding"  # seeding | ready | failed
    reason: str | None = "loading_history"
    pending: list[Candle] = field(default_factory=list)
    recent: OrderedDict[int, Candle] = field(default_factory=OrderedDict)
    forming: Candle | None = None
    consumers: set[str] = field(default_factory=set)  # browser connections (execution)
    context_refs: int = 0  # execution keys that use this key as higher-timeframe context
    dirty: bool = False
    last_live: float = 0.0
    signature: tuple[Any, ...] = ()
    task: asyncio.Task[None] | None = None
    generation: int = 0

    @property
    def needed(self) -> bool:
        return bool(self.consumers) or self.context_refs > 0


class AnalysisService:
    def __init__(
        self,
        market: MarketDataEngine,
        *,
        config: AnalysisConfig = DEFAULT_CONFIG,
        include_debug: bool = False,
        lookback: int = ANALYSIS_LOOKBACK,
        live_interval: float = LIVE_INTERVAL,
        live_min_interval: float = LIVE_MIN_INTERVAL,
        loop_interval: float = LOOP_INTERVAL,
    ) -> None:
        self.market = market
        self.config = config
        self.include_debug = include_debug
        self.lookback = lookback
        self.live_interval = live_interval
        self.live_min_interval = live_min_interval
        self.loop_interval = loop_interval
        self._entries: dict[AppKey, _Entry] = {}
        self._on_demand: dict[AppKey, tuple[float, MarketAnalyzer, Candle | None]] = {}
        self._loop: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self.stats = {"full_sent": 0, "live_sent": 0, "reseeds": 0, "seed_failures": 0}
        self.listeners: list[AnalysisListener] = []
        market.candle_listeners.append(self.on_candle)
        market.resync_listeners.append(self.on_resync)

    # --- lifecycle ---------------------------------------------------------------------
    async def start(self) -> None:
        self._loop = asyncio.create_task(self._live_loop(), name="analysis-live")

    async def stop(self) -> None:
        tasks = [e.task for e in self._entries.values() if e.task is not None]
        if self._loop is not None:
            tasks.append(self._loop)
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    # --- consumers ---------------------------------------------------------------------
    async def subscribe(self, consumer: str, symbol: str, timeframe: Timeframe) -> None:
        key = (symbol, timeframe)
        async with self._lock:
            entry = self._entry(key)
            first = not entry.consumers
            entry.consumers.add(consumer)
            if first:
                for ctf in context_timeframes(timeframe):
                    await self._acquire_context((symbol, ctf))
        self.market.publisher.send_to([consumer], self._full_event(entry))

    async def unsubscribe(self, consumer: str, symbol: str, timeframe: Timeframe) -> None:
        key = (symbol.strip().upper(), timeframe)
        async with self._lock:
            await self._release_consumer(consumer, key)

    async def release_all(self, consumer: str) -> None:
        async with self._lock:
            for key in [k for k, e in self._entries.items() if consumer in e.consumers]:
                await self._release_consumer(consumer, key)

    async def _release_consumer(self, consumer: str, key: AppKey) -> None:
        entry = self._entries.get(key)
        if entry is None or consumer not in entry.consumers:
            return
        entry.consumers.discard(consumer)
        if not entry.consumers:
            for ctf in context_timeframes(key[1]):
                await self._release_context((key[0], ctf))
        self._drop_if_unused(key)

    async def _acquire_context(self, key: AppKey) -> None:
        entry = self._entry(key)
        entry.context_refs += 1
        if entry.context_refs == 1:
            try:
                await self.market.subscribe(INTERNAL_CONSUMER, key[0], key[1])
            except MarketDataError as exc:
                logger.warning(
                    "analysis.context_subscribe_failed",
                    extra={"fields": {"key": _label(key), "error": str(exc)}},
                )

    async def _release_context(self, key: AppKey) -> None:
        entry = self._entries.get(key)
        if entry is None:
            return
        entry.context_refs = max(0, entry.context_refs - 1)
        if entry.context_refs == 0:
            await self.market.unsubscribe(INTERNAL_CONSUMER, key[0], key[1])
        self._drop_if_unused(key)

    def _entry(self, key: AppKey) -> _Entry:
        entry = self._entries.get(key)
        if entry is None:
            entry = _Entry(key)
            self._entries[key] = entry
            self._seed(entry)
        return entry

    def _drop_if_unused(self, key: AppKey) -> None:
        entry = self._entries.get(key)
        if entry is not None and not entry.needed:
            if entry.task is not None:
                entry.task.cancel()
            del self._entries[key]

    # --- seeding ---------------------------------------------------------------------------
    def _seed(self, entry: _Entry) -> None:
        entry.generation += 1
        if entry.task is not None:
            entry.task.cancel()
        entry.state, entry.reason = "seeding", "loading_history"
        entry.task = asyncio.create_task(self._seed_task(entry, entry.generation))

    async def _seed_task(self, entry: _Entry, generation: int) -> None:
        symbol, timeframe = entry.key
        attempt = 0
        while True:
            entry.pending.clear()
            try:
                market = self.market.symbols.get(symbol)
                history = await self.market.candles.history(market, timeframe, limit=self.lookback)
                break
            except MarketDataError as exc:
                self.stats["seed_failures"] += 1
                delay = SEED_RETRY_SECONDS[min(attempt, len(SEED_RETRY_SECONDS) - 1)]
                attempt += 1
                entry.state, entry.reason = "failed", "history_unavailable"
                logger.warning(
                    "analysis.seed_failed",
                    extra={"fields": {"key": _label(entry.key), "error": str(exc)}},
                )
                self._publish_full(entry)
                await asyncio.sleep(delay)
        if generation != entry.generation:
            return
        tick = float(market.tick_size) if market.tick_size else None
        analyzer = MarketAnalyzer(symbol, timeframe, tick_size=tick, config=self.config)
        entry.recent.clear()
        forming: Candle | None = None
        for candle in [*history, *entry.pending]:
            if not candle.is_closed:
                if forming is None or candle.open_ms >= forming.open_ms:
                    forming = candle
                continue
            if analyzer.last_open_ms is None or candle.open_ms > analyzer.last_open_ms:
                analyzer.update(candle)
                self._remember(entry, candle)
        entry.pending.clear()
        entry.analyzer = analyzer
        last = analyzer.last_open_ms
        entry.forming = forming if forming and (last is None or forming.open_ms > last) else None
        entry.state = "ready"
        entry.reason = analyzer.readiness()
        logger.info(
            "analysis.seeded",
            extra={"fields": {"key": _label(entry.key), "candles": analyzer.candles}},
        )
        self._publish_full(entry)
        self._publish_dependents(entry.key)
        self._notify("on_seeded", entry.key, analyzer)

    def _notify(self, method: str, *args: Any) -> None:
        for listener in self.listeners:
            try:
                getattr(listener, method)(*args)
            except Exception:
                logger.exception("analysis.listener_failed")

    def _remember(self, entry: _Entry, candle: Candle) -> None:
        entry.recent[candle.open_ms] = candle
        while len(entry.recent) > RECENT_CLOSED:
            entry.recent.popitem(last=False)

    def _reseed(self, entry: _Entry, reason: str) -> None:
        self.stats["reseeds"] += 1
        logger.info(
            "analysis.reseed", extra={"fields": {"key": _label(entry.key), "reason": reason}}
        )
        self._seed(entry)
        self._publish_full(entry)

    # --- feed listeners ---------------------------------------------------------------------
    def on_candle(self, candle: Candle) -> None:
        entry = self._entries.get((candle.symbol, candle.timeframe))
        if entry is None:
            return
        if entry.state != "ready" or entry.analyzer is None:
            if candle.is_closed:
                entry.pending.append(candle)
            return
        analyzer = entry.analyzer
        if not candle.is_closed:
            if analyzer.last_open_ms is None or candle.open_ms > analyzer.last_open_ms:
                entry.forming = candle
                entry.dirty = True
                self._notify("on_forming", entry.key)
            return
        last = analyzer.last_open_ms
        if last is not None and candle.open_ms <= last:
            known = entry.recent.get(candle.open_ms)
            if known is None or not known.same_values(candle):
                self._reseed(entry, "corrected_candle")
            return
        if last is not None and candle.open_ms != last + candle.timeframe.milliseconds:
            self._reseed(entry, "gap")
            return
        try:
            analyzer.update(candle)
        except AnalysisOrderError:
            self._reseed(entry, "order")
            return
        self._remember(entry, candle)
        if entry.forming is not None and entry.forming.open_ms <= candle.open_ms:
            entry.forming = None
        entry.reason = analyzer.readiness()
        self._publish_full(entry)
        self._publish_dependents(entry.key)
        self._notify("on_closed", entry.key, analyzer)

    def on_resync(self, key: AppKey) -> None:
        entry = self._entries.get(key)
        if entry is not None:
            self._reseed(entry, "resync")

    # --- snapshots ---------------------------------------------------------------------------
    def _context(self, key: AppKey) -> list[MtfFrame]:
        frames: list[MtfFrame] = []
        for ctf in context_timeframes(key[1]):
            ctx = self._entries.get((key[0], ctf))
            if ctx is not None and ctx.analyzer is not None and ctx.state == "ready":
                frames.append(ctx.analyzer.frame())
            else:
                frames.append(not_ready_frame(ctf))
        return frames

    def analyzer(self, key: AppKey) -> MarketAnalyzer | None:
        entry = self._entries.get(key)
        return entry.analyzer if entry is not None and entry.state == "ready" else None

    def forming(self, key: AppKey) -> Candle | None:
        entry = self._entries.get(key)
        return entry.forming if entry is not None else None

    def consumers(self, key: AppKey) -> set[str]:
        entry = self._entries.get(key)
        return set(entry.consumers) if entry is not None else set()

    def context_frames(self, key: AppKey) -> list[MtfFrame]:
        return self._context(key)

    def snapshot(self, key: AppKey) -> AnalysisSnapshot | None:
        entry = self._entries.get(key)
        if entry is None or entry.analyzer is None or entry.state != "ready":
            return None
        return entry.analyzer.snapshot(
            entry.forming, context=self._context(key), include_debug=self.include_debug
        )

    def _not_ready(self, entry: _Entry) -> dict[str, Any]:
        symbol, timeframe = entry.key
        return {
            "kind": "full",
            "symbol": symbol,
            "timeframe": timeframe.value,
            "analysis_ready": False,
            "reason": entry.reason or "loading_history",
            "candles_analyzed": entry.analyzer.candles if entry.analyzer else 0,
        }

    def full_payload(self, key: AppKey) -> dict[str, Any] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        return self._full(entry, self.snapshot(key))

    def _full(self, entry: _Entry, snap: AnalysisSnapshot | None) -> dict[str, Any]:
        if snap is None:
            return self._not_ready(entry)
        return {"kind": "full", **snapshot_payload(snap)}

    def _full_event(self, entry: _Entry) -> EventEnvelope:
        return EventEnvelope.of(
            EventType.ANALYSIS_UPDATE, self._full(entry, self.snapshot(entry.key))
        )

    def _publish_full(self, entry: _Entry) -> None:
        if not entry.consumers:
            return
        snap = self.snapshot(entry.key)
        event = EventEnvelope.of(EventType.ANALYSIS_UPDATE, self._full(entry, snap))
        self.market.publisher.send_to(entry.consumers, event)
        self.stats["full_sent"] += 1
        entry.dirty = False
        entry.last_live = time.monotonic()
        entry.signature = developing_signature(snap) if snap else ()

    def _publish_dependents(self, key: AppKey) -> None:
        """A higher-timeframe change alters the MTF context of the keys that use it."""
        symbol, timeframe = key
        for other in list(self._entries.values()):
            if other.key[0] == symbol and timeframe in context_timeframes(other.key[1]):
                self._publish_full(other)

    async def _live_loop(self) -> None:
        while True:
            await asyncio.sleep(self.loop_interval)
            now = time.monotonic()
            for entry in list(self._entries.values()):
                if not entry.dirty or not entry.consumers or entry.state != "ready":
                    continue
                elapsed = now - entry.last_live
                if elapsed < self.live_min_interval:
                    continue
                snap = self.snapshot(entry.key)
                if snap is None:
                    continue
                signature = developing_signature(snap)
                if signature == entry.signature and elapsed < self.live_interval:
                    continue
                payload = live_payload({"kind": "live", **snapshot_payload(snap)})
                self.market.publisher.send_to(
                    entry.consumers, EventEnvelope.of(EventType.ANALYSIS_UPDATE, payload)
                )
                self.stats["live_sent"] += 1
                entry.signature, entry.dirty, entry.last_live = signature, False, now

    # --- REST (works without a live subscription) ---------------------------------------
    async def latest(self, symbol: str, timeframe: Timeframe) -> dict[str, Any]:
        key = (symbol, timeframe)
        live = self.full_payload(key)
        if live is not None and live.get("analysis_ready"):
            return live
        analyzer, forming = await self._on_demand_analyzer(key)
        frames = []
        for ctf in context_timeframes(timeframe):
            ctx, _ = await self._on_demand_analyzer((symbol, ctf))
            frames.append(ctx.frame())
        snap = analyzer.snapshot(forming, context=frames, include_debug=self.include_debug)
        return {"kind": "full", **snapshot_payload(snap)}

    async def history(self, symbol: str, timeframe: Timeframe, limit: int) -> dict[str, Any]:
        key = (symbol, timeframe)
        entry = self._entries.get(key)
        if entry is not None and entry.analyzer is not None and entry.state == "ready":
            analyzer = entry.analyzer
        else:
            analyzer, _ = await self._on_demand_analyzer(key)
        limit = max(1, min(limit, HISTORY_MAX_ROWS))
        rows = list(analyzer.rows)[-limit:]
        since = rows[0]["time"] if rows else 0
        events = [e for e in [*analyzer.swing.events, *analyzer.internal.events] if e.time >= since]
        sweeps = [s for s in analyzer.liquidity.sweeps if s.time >= since]
        return {
            "symbol": symbol,
            "timeframe": timeframe.value,
            "analysis_ready": analyzer.readiness() is None,
            "rows": to_payload(rows),
            "structure_events": to_payload(sorted(events, key=lambda e: (e.time, e.layer))),
            "sweeps": to_payload(sweeps),
        }

    async def on_demand(self, key: AppKey) -> tuple[MarketAnalyzer, Candle | None, list[MtfFrame]]:
        """Analyzer for any key (live if subscribed, else built from REST history, cached)."""
        analyzer, forming = await self._on_demand_analyzer(key)
        frames = []
        for ctf in context_timeframes(key[1]):
            ctx, _ = await self._on_demand_analyzer((key[0], ctf))
            frames.append(ctx.frame())
        return analyzer, forming, frames

    async def _on_demand_analyzer(self, key: AppKey) -> tuple[MarketAnalyzer, Candle | None]:
        entry = self._entries.get(key)
        if entry is not None and entry.analyzer is not None and entry.state == "ready":
            return entry.analyzer, entry.forming
        cached = self._on_demand.get(key)
        if cached is not None and time.monotonic() - cached[0] < ON_DEMAND_TTL:
            return cached[1], cached[2]
        symbol, timeframe = key
        market = self.market.symbols.get(symbol)
        history = await self.market.candles.history(market, timeframe, limit=self.lookback)
        tick = float(market.tick_size) if market.tick_size else None
        analyzer = MarketAnalyzer(symbol, timeframe, tick_size=tick, config=self.config)
        forming = None
        for candle in history:
            if candle.is_closed:
                analyzer.update(candle)
            else:
                forming = candle
        self._on_demand[key] = (time.monotonic(), analyzer, forming)
        if len(self._on_demand) > 32:
            oldest = min(self._on_demand, key=lambda k: self._on_demand[k][0])
            del self._on_demand[oldest]
        return analyzer, forming

    def health(self) -> dict[str, Any]:
        return {
            "analyzers": {
                _label(k): {
                    "state": e.state,
                    "reason": e.reason,
                    "candles": e.analyzer.candles if e.analyzer else 0,
                    "consumers": len(e.consumers),
                    "context_refs": e.context_refs,
                }
                for k, e in self._entries.items()
            },
            **self.stats,
        }


def _label(key: AppKey) -> str:
    return f"{key[0]}:{key[1].value}"
