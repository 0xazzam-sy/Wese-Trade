"""Live execution timing (1m / 5m / 10m) for active Strategy 4.2 signals.

* One stream per viewed execution chart (symbol x 1m/5m/10m); incremental per closed candle.
* Parent = the open Strategy 4.2 forward-test signal of the mapped higher timeframes
  (1m/5m <- 15m/30m, 10m <- 30m/1h). Without one, the stream shows NO SETUP.
* A BUY / SELL is confirmed only on a candle observed CLOSING live (never from seeded or
  catch-up history) and is persisted once; its lifecycle advances on every closed candle,
  including candles closed while the app was not running (restart catch-up).
* Live microstructure (books5 + trades) is optional confirmation; failures fall back to
  candle/structure logic and never break the stream.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Protocol

from app.analysis.engine import MarketAnalyzer
from app.analysis.service import AnalysisService
from app.core.logging import get_logger
from app.db.session import Database
from app.execution import engine, store
from app.execution.analyzer import ExecAnalyzer
from app.execution.codec import evaluation_payload, marker_payload, micro_payload, signal_payload
from app.execution.micro import MicroFeed
from app.execution.models import (
    EXECUTION_TIMEFRAMES,
    EXECUTION_VERSION,
    Decision,
    Evaluation,
    ExecState,
    ExecutionSignal,
    Micro,
    ParentSetup,
)
from app.market_data.engine import MarketDataEngine
from app.market_data.timeframes import Timeframe
from app.signal_engine.models import Signal
from app.strategy43.config import FAMILY_AR, tier
from app.telegram.models import SignalAlert
from app.websocket.events import EventEnvelope, EventType

logger = get_logger(__name__)

AppKey = tuple[str, Timeframe]
LOOP_INTERVAL = 1.0
FIXED_TIME = datetime(2000, 1, 1, tzinfo=UTC)
KEEP_SIGNALS = 50
FRESH_CLOSES = 2  # a confirmation needs a candle that closed at most this many steps ago
PARENT_TIMEFRAMES = ("15m", "30m", "1h")


class ParentSource(Protocol):
    """The primary-timeframe engine providing parents (Strategy 4.3 in v1.2)."""

    name: str

    @property
    def streams(self) -> Mapping[AppKey, Any]: ...


AlertSink = Callable[[SignalAlert], None]


@dataclass(slots=True)
class _Stream:
    key: AppKey
    analyzer: ExecAnalyzer = field(default_factory=ExecAnalyzer)
    signals: list[ExecutionSignal] = field(default_factory=list)  # oldest first
    current: Evaluation | None = None
    loaded: bool = False
    micro: bool = False
    parents_seen: tuple[tuple[str, str], ...] = ()


def parent_from_signal(s: Signal, strategy: str) -> ParentSetup:
    p = s.plan
    return ParentSetup(
        signal_id=s.id,
        strategy=strategy,
        strategy_version=s.strategy_version,
        symbol=s.symbol,
        timeframe=s.timeframe,
        side=s.side.sign,
        family=s.family.value,
        score=round(s.score, 1),
        state=s.state.value,
        confirmed_time=s.confirmed_time,
        entry_low=p.entry_low,
        entry_high=p.entry_high,
        entry=p.preferred_entry,
        stop=p.stop,
        invalidation=p.invalidation,
        targets=(p.targets[0].price, p.targets[1].price, p.targets[2].price),
    )


class ExecutionService:
    def __init__(
        self,
        analysis: AnalysisService,
        market: MarketDataEngine,
        database: Database | None,
        parent_source: ParentSource | None,
        micro: MicroFeed | None = None,
        *,
        alerts: AlertSink | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.analysis = analysis
        self.market = market
        self.database = database
        self.parent_source = parent_source
        self.alerts = alerts
        self.micro = micro
        self.clock = clock
        self.streams: dict[AppKey, _Stream] = {}
        self.stats: dict[str, Any] = {"evaluations": 0, "confirmed": 0, "persist_errors": 0}
        self._queue: asyncio.Queue[ExecutionSignal] = asyncio.Queue()
        self._tasks: list[asyncio.Task[Any]] = []
        self._loading: set[asyncio.Future[None]] = set()
        analysis.listeners.append(self)

    # --- lifecycle ----------------------------------------------------------------------------
    async def start(self, *, background_loop: bool = True) -> None:
        self._tasks = [asyncio.create_task(self._writer(), name="execution-writer")]
        if background_loop:
            self._tasks.append(asyncio.create_task(self._loop(), name="execution-loop"))

    async def stop(self) -> None:
        await self.flush()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if self.micro is not None:
            await self.micro.close()

    async def flush(self) -> None:
        if self._tasks and not self._tasks[0].done():
            await self._queue.join()

    # --- parents ------------------------------------------------------------------------------
    def parents(self, symbol: str) -> list[ParentSetup]:
        src = self.parent_source
        if src is None:
            return []
        out = []
        for tf in PARENT_TIMEFRAMES:
            stream = src.streams.get((symbol, Timeframe(tf)))
            if stream is not None and stream.tracker.active is not None:
                out.append(parent_from_signal(stream.tracker.active, src.name))
        return out

    def _parent_state(self, parent: ParentSetup) -> str:
        for p in self.parents(parent.symbol):
            if p.signal_id == parent.signal_id:
                return p.state
        return "closed"

    # --- streams ------------------------------------------------------------------------------
    @staticmethod
    def handles(key: AppKey) -> bool:
        return key[1].value in EXECUTION_TIMEFRAMES

    def _stream(self, key: AppKey, analyzer: MarketAnalyzer) -> _Stream:
        stream = self.streams.get(key)
        if stream is None:
            stream = _Stream(key)
            self.streams[key] = stream
            if self.micro is not None:
                try:
                    self.micro.acquire(key[0])
                    stream.micro = True
                except Exception:  # live microstructure is optional
                    logger.exception("execution.micro_acquire_failed")
            if self.database is not None:
                task = asyncio.ensure_future(self._load(stream))
                self._loading.add(task)
                task.add_done_callback(self._loading.discard)
            else:
                stream.loaded = True
        if len(analyzer.series):
            stream.analyzer.sync(analyzer.series.tail(len(analyzer.series)))
        return stream

    def _drop(self, key: AppKey) -> None:
        stream = self.streams.pop(key, None)
        if stream is not None and stream.micro and self.micro is not None:
            self.micro.release(key[0])

    async def _load(self, stream: _Stream) -> None:
        """Restore this stream's persisted signals and advance open ones over candles that
        closed while we were not watching (lifecycle only; never new signals)."""
        if self.database is None:
            return
        try:
            async with self.database.session_factory() as session:
                rows = await store.stream_signals(session, stream.key[0], stream.key[1].value)
        except Exception:
            logger.exception("execution.load_failed")
            rows = []
        known = {s.id for s in stream.signals}
        stream.signals = sorted(
            [*rows, *[s for s in stream.signals if s.id not in {r.id for r in rows}]],
            key=lambda s: s.confirmed_time,
        )[-KEEP_SIGNALS:]
        analyzer = self.analysis.analyzer(stream.key)
        if analyzer is not None and len(analyzer.series):
            bars = analyzer.series.tail(len(analyzer.series))
            for s in stream.signals:
                if not s.is_open or s.id in known:
                    continue
                for bar in bars:
                    if self._advance(s, bar.high, bar.low, bar.close_time, alert=False):
                        self._persist(s)
        stream.loaded = True
        self._evaluate(stream, confirm=False)

    # --- AnalysisListener ---------------------------------------------------------------------
    def on_seeded(self, key: AppKey, analyzer: MarketAnalyzer) -> None:
        if not self.handles(key) or not self.analysis.consumers(key):
            return
        stream = self._stream(key, analyzer)
        self._evaluate(stream, confirm=False)

    def on_closed(self, key: AppKey, analyzer: MarketAnalyzer) -> None:
        if not self.handles(key):
            return
        if not self.analysis.consumers(key):
            self._drop(key)
            return
        stream = self._stream(key, analyzer)
        bar = analyzer.series.last
        for s in stream.signals:
            if s.is_open and self._advance(s, bar.high, bar.low, bar.close_time, alert=True):
                self._persist(s)
        fresh = self.clock() - bar.close_time <= FRESH_CLOSES * key[1].seconds
        self._evaluate(stream, confirm=fresh and stream.loaded)

    def on_forming(self, key: AppKey) -> None:
        return

    def _advance(
        self, s: ExecutionSignal, high: float, low: float, close_time: int, *, alert: bool
    ) -> bool:
        hits, state = s.targets_hit, s.state
        changed = engine.advance(s, high, low, close_time, self._parent_state(s.parent))
        if changed and alert:
            events = [f"TP{n}" for n in range(hits + 1, min(s.targets_hit, 3) + 1)]
            if s.state is ExecState.STOPPED and state is not ExecState.STOPPED:
                events.append("STOPPED")
            elif s.state is ExecState.EXPIRED and state is not ExecState.EXPIRED:
                events.append("EXPIRED")
            for event in events:
                self._alert(s, event)
        return changed

    def _alert(self, s: ExecutionSignal, event: str) -> None:
        if self.alerts is None:
            return
        try:
            p = s.plan
            risk = p.risk or 1.0
            rr = tuple(round(abs(t - p.entry) / risk, 2) for t in p.targets)
            precision = None
            with contextlib.suppress(Exception):
                precision = self.market.symbols.get(s.symbol).price_precision
            parent_tier = tier(s.parent.score)
            self.alerts(
                SignalAlert(
                    signal_id=s.id,
                    event=event,
                    symbol=s.symbol,
                    side=s.side,
                    timeframe=s.timeframe,
                    primary_timeframe=s.parent.timeframe,
                    execution_timeframe=s.timeframe,
                    entry=p.entry,
                    stop=p.stop,
                    targets=p.targets,
                    rr=(rr[0], rr[1], rr[2]),
                    tier=parent_tier,
                    score=s.parent.score,
                    timing_score=s.score,
                    family_ar=FAMILY_AR.get(s.parent.family, s.parent.family),
                    signal_time=s.confirmed_time,
                    price_precision=precision,
                )
            )
        except Exception:  # Telegram can never break the engine
            logger.exception("execution.alert_failed")

    # --- evaluation ---------------------------------------------------------------------------
    def _micro(self, symbol: str) -> Micro | None:
        if self.micro is None:
            return None
        try:
            return self.micro.snapshot(symbol)
        except Exception:
            logger.exception("execution.micro_snapshot_failed")
            return Micro(status="unavailable")

    def _evaluate(self, stream: _Stream, *, confirm: bool) -> None:
        symbol, tf = stream.key[0], stream.key[1].value
        analyzer = self.analysis.analyzer(stream.key)
        candidates = self.parents(symbol)
        stream.parents_seen = tuple(sorted((p.signal_id, p.state) for p in candidates))
        parent, conflict = engine.select_parent(tf, candidates)
        signal = None
        if parent is not None:
            for s in reversed(stream.signals):
                if s.parent.signal_id == parent.signal_id:
                    signal = s
                    break
        features = None
        if analyzer is not None and len(analyzer.series) and stream.analyzer.count:
            bar = analyzer.series.last
            snap = analyzer.snapshot(None, generated_at=FIXED_TIME)
            features = stream.analyzer.features(bar, snap, analyzer.tick)
        ev = engine.evaluate(
            symbol,
            tf,
            features,
            parent,
            conflict=conflict,
            micro=self._micro(symbol),
            signal=signal,
        )
        self.stats["evaluations"] += 1
        new = None
        if confirm and features is not None and ev.trigger is not None and signal is None:
            new = engine.confirm(ev, features)
        if new is not None:
            stream.signals = [*stream.signals, new][-KEEP_SIGNALS:]
            self.stats["confirmed"] += 1
            self._persist(new)
            self._alert(new, "NEW")
            logger.info(
                "execution.confirmed",
                extra={
                    "fields": {
                        "id": new.id,
                        "side": new.side,
                        "score": new.score,
                        "parent": new.parent.signal_id,
                        "parent_timeframe": new.parent.timeframe,
                    }
                },
            )
        elif signal is None and ev.trigger is not None:
            # display-only evaluation (seeded / catch-up / stale candle): never a BUY / SELL
            # without a persisted confirmation
            ev = replace(
                ev,
                decision=Decision.WAIT,
                trigger=None,
                headline="بانتظار شمعة تأكيد جديدة على هذا الفريم.",
            )
        stream.current = ev
        self._publish(stream)

    # --- persistence --------------------------------------------------------------------------
    def _persist(self, s: ExecutionSignal) -> None:
        if self.database is not None:
            self._queue.put_nowait(copy.deepcopy(s))  # snapshot NOW: the live object changes

    async def _writer(self) -> None:
        while True:
            s = await self._queue.get()
            try:
                if self.database is not None:
                    async with self.database.session_factory() as session:
                        await store.save(session, s)
            except Exception:
                self.stats["persist_errors"] += 1
                logger.exception("execution.persist_failed")
            finally:
                self._queue.task_done()

    # --- loop: parent changes, dropped viewers ------------------------------------------------
    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(LOOP_INTERVAL)
            try:
                self.tick()
            except Exception:
                logger.exception("execution.tick_failed")

    def tick(self) -> None:
        for key, stream in list(self.streams.items()):
            if not self.analysis.consumers(key):
                self._drop(key)
                continue
            seen = tuple(sorted((p.signal_id, p.state) for p in self.parents(key[0])))
            if seen != stream.parents_seen and stream.loaded:
                self._evaluate(stream, confirm=False)  # parent appeared/changed: refresh now

    # --- UI -----------------------------------------------------------------------------------
    def state(self, key: AppKey) -> dict[str, Any]:
        stream = self.streams.get(key)
        analyzer = self.analysis.analyzer(key)
        price = analyzer.series.last.close if analyzer is not None and len(analyzer.series) else 0.0
        current = stream.current if stream else None
        latest = None
        if stream is not None and current is not None and current.parent is not None:
            for s in reversed(stream.signals):
                if s.parent.signal_id == current.parent.signal_id:
                    latest = s
                    break
        return {
            "symbol": key[0],
            "timeframe": key[1].value,
            "execution_version": EXECUTION_VERSION,
            "evaluation": evaluation_payload(current) if current else None,
            "signal": signal_payload(latest) if latest else None,
            "markers": [marker_payload(s) for s in stream.signals] if stream else [],
            "overlay": stream.analyzer.overlay(price) if stream and stream.analyzer.count else None,
            "micro": micro_payload(current.micro) if current else None,
        }

    def _publish(self, stream: _Stream) -> None:
        consumers = self.analysis.consumers(stream.key)
        if consumers:
            self.market.publisher.send_to(
                consumers, EventEnvelope.of(EventType.EXECUTION_UPDATE, self.state(stream.key))
            )

    def subscribe(self, consumer: str, key: AppKey) -> None:
        if not self.handles(key):
            return
        if key in self.streams:
            self.market.publisher.send_to(
                [consumer], EventEnvelope.of(EventType.EXECUTION_UPDATE, self.state(key))
            )

    async def signals(self, symbol: str, timeframe: str, limit: int = 50) -> list[dict[str, Any]]:
        if self.database is None:
            return []
        async with self.database.session_factory() as session:
            rows = await store.stream_signals(session, symbol, timeframe, limit)
        return [signal_payload(s) for s in rows]

    def health(self) -> dict[str, Any]:
        return {
            "version": EXECUTION_VERSION,
            "streams": {
                f"{k[0]}:{k[1].value}": {
                    "decision": s.current.decision.value if s.current else None,
                    "open_signals": sum(1 for x in s.signals if x.is_open),
                }
                for k, s in self.streams.items()
            },
            "parent_source": self.parent_source.name if self.parent_source is not None else None,
            "micro": self.micro.health() if self.micro is not None else None,
            **self.stats,
        }
