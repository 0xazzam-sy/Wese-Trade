"""Live signals: SignalEngine + SignalTracker over the live analyzers (same code as replay).

* Confirmation: when an execution candle closes at T, evaluation waits until every
  higher-timeframe analyzer whose candle also closes at T has processed it (max
  CONTEXT_WAIT_SECONDS), so live sees exactly what the backtest sees at T. The forming
  candle is never part of a confirmed evaluation.
* Developing: forming-candle evaluations at most every `developing_min_interval_seconds`
  (`signal.developing`); display only — never persisted, never counted as a trade.
* Lifecycle: every closed candle advances the open signal (SignalTracker); transitions are
  published (`signal.updated` / `signal.closed`) and persisted.
* Dedupe: the tracker refuses ids it has seen; ids of recent persisted signals are loaded
  after (re)seeding, so reconnects/restarts never re-emit a signal.
* A stale or reconnecting market stream makes every evaluation NEUTRAL.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any

from app.analysis.engine import MarketAnalyzer
from app.analysis.multi_timeframe.context import context_timeframes
from app.analysis.service import AnalysisService
from app.core.logging import get_logger
from app.db.session import Database
from app.market_data.engine import MarketDataEngine
from app.market_data.services.subscription_manager import AppKey
from app.services import signal_store
from app.signal_engine.config import DEFAULT_SIGNAL_CONFIG, SignalConfig
from app.signal_engine.engine import SignalEngine
from app.signal_engine.lifecycle import SignalTracker
from app.signal_engine.models import Signal, SignalEvaluation
from app.signal_engine.runtime import evaluate_closed, evaluate_developing
from app.signal_engine.serialize import evaluation_payload, signal_payload
from app.websocket.events import EventEnvelope, EventType

logger = get_logger(__name__)

CONTEXT_WAIT_SECONDS = 15.0
LOOP_INTERVAL = 1.0


@dataclass
class _Stream:
    key: AppKey
    tracker: SignalTracker
    current: SignalEvaluation | None = None
    developing: SignalEvaluation | None = None
    pending_close: int | None = None  # close time awaiting context
    pending_since: float = 0.0
    seed_pending: bool = False  # display-only evaluation of the seeded history
    seed_since: float = 0.0
    forming_dirty: bool = False
    last_developing: float = 0.0
    last_confirmed: Signal | None = None
    recent: list[Signal] = field(default_factory=list)


class SignalService:
    def __init__(
        self,
        analysis: AnalysisService,
        market: MarketDataEngine,
        database: Database | None,
        config: SignalConfig = DEFAULT_SIGNAL_CONFIG,
    ) -> None:
        self.analysis = analysis
        self.market = market
        self.database = database
        self.config = config
        self.engine = SignalEngine(config)
        self.streams: dict[AppKey, _Stream] = {}
        self._tasks: set[asyncio.Task[Any]] = set()
        self._loop: asyncio.Task[None] | None = None
        self.stats = {"confirmed": 0, "developing_sent": 0, "evaluations": 0}
        analysis.listeners.append(self)

    # --- lifecycle --------------------------------------------------------------------
    async def start(self) -> None:
        self._loop = asyncio.create_task(self._run(), name="signals-live")

    async def stop(self) -> None:
        tasks = [*self._tasks, *([self._loop] if self._loop else [])]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    def _spawn(self, coro: Any) -> None:
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # --- subscriptions (browser) ---------------------------------------------------------
    def subscribe(self, consumer: str, key: AppKey) -> None:
        """Send the current signal state of an execution stream to a new subscriber."""
        stream = self.streams.get(key)
        if stream is not None:
            self.market.publisher.send_to([consumer], self._state_event(stream))

    def _stream(self, key: AppKey) -> _Stream:
        stream = self.streams.get(key)
        if stream is None:
            tracker = SignalTracker(
                key[0], key[1].value, self.config, step_seconds=key[1].seconds, sink=self._sink(key)
            )
            stream = _Stream(key, tracker)
            self.streams[key] = stream
        return stream

    # --- AnalysisListener ----------------------------------------------------------------
    def on_seeded(self, key: AppKey, analyzer: MarketAnalyzer) -> None:
        # A context timeframe finishing its seed may complete a pending seed evaluation.
        for other in list(self.streams.values()):
            if other.seed_pending and other.key != key and other.key[0] == key[0]:
                self._try_seed(other)
        if not self.analysis.consumers(key):
            return
        stream = self._stream(key)
        stream.pending_close = None
        stream.seed_pending = True
        stream.seed_since = time.monotonic()
        if self.database is not None:
            self._spawn(self._load_seen(stream))
        self._try_seed(stream)

    def on_closed(self, key: AppKey, analyzer: MarketAnalyzer) -> None:
        if self.analysis.consumers(key):
            stream = self._stream(key)
            stream.tracker.on_bar(analyzer.series.last)
            stream.pending_close = analyzer.series.last.close_time
            stream.pending_since = time.monotonic()
            stream.developing = None
            self._try_evaluate(stream)
        # A higher-timeframe close may complete a pending execution evaluation.
        for other in list(self.streams.values()):
            if (
                other.pending_close is not None
                and key[0] == other.key[0]
                and key[1] in context_timeframes(other.key[1])
            ):
                self._try_evaluate(other)

    def on_forming(self, key: AppKey) -> None:
        stream = self.streams.get(key)
        if stream is not None:
            stream.forming_dirty = True

    # --- evaluation ---------------------------------------------------------------------------
    def _context_ready(self, stream: _Stream) -> bool:
        close = stream.pending_close
        if close is None:
            return False
        for ctf in context_timeframes(stream.key[1]):
            if close % ctf.seconds:
                continue  # no context candle closes at this moment
            analyzer = self.analysis.analyzer((stream.key[0], ctf))
            if analyzer is None or not len(analyzer.series):
                continue  # not ready: the engine's gate decides (frame.ready = False)
            if analyzer.series.last.close_time < close:
                return False
        return True

    def _stale(self, key: AppKey) -> bool:
        return self.market.stream_state(key) != "live"

    def _try_evaluate(self, stream: _Stream, *, force: bool = False) -> None:
        if stream.pending_close is None:
            return
        if not force and not self._context_ready(stream):
            return
        analyzer = self.analysis.analyzer(stream.key)
        if analyzer is None or analyzer.series.last.close_time != stream.pending_close:
            stream.pending_close = None
            return
        stream.pending_close = None
        frames = self.analysis.context_frames(stream.key)
        ev = evaluate_closed(self.engine, analyzer, frames, market_stale=self._stale(stream.key))
        self.stats["evaluations"] += 1
        stream.current = ev
        stream.tracker.on_evaluation(ev, analyzer.series.last)
        self._publish(stream, EventType.SIGNAL_UPDATED, {"evaluation": evaluation_payload(ev)})

    def _try_seed(self, stream: _Stream, *, force: bool = False) -> None:
        """Evaluate the last seeded candle so a new viewer sees the current state at once.

        Display only: the result never reaches the tracker, so joining late can never
        create a (stale) signal. A non-NEUTRAL result is withheld because no live signal
        was issued for that candle; the next close is evaluated normally.
        """
        analyzer = self.analysis.analyzer(stream.key)
        if analyzer is None or not len(analyzer.series):
            return
        if not force:
            for ctf in context_timeframes(stream.key[1]):
                ctx = self.analysis.analyzer((stream.key[0], ctf))
                if ctx is None or not len(ctx.series):
                    return
        stream.seed_pending = False
        if stream.current is not None:
            return
        frames = self.analysis.context_frames(stream.key)
        ev = evaluate_closed(self.engine, analyzer, frames, market_stale=self._stale(stream.key))
        if ev.is_trade:
            return
        stream.current = ev
        self._publish(stream, EventType.SIGNAL_UPDATED, {"evaluation": evaluation_payload(ev)})

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(LOOP_INTERVAL)
            now = time.monotonic()
            for stream in list(self.streams.values()):
                if not self.analysis.consumers(stream.key):
                    continue
                if (
                    stream.pending_close is not None
                    and now - stream.pending_since > CONTEXT_WAIT_SECONDS
                ):
                    logger.warning(
                        "signals.context_timeout", extra={"fields": {"key": _label(stream.key)}}
                    )
                    self._try_evaluate(stream, force=True)
                if stream.seed_pending and now - stream.seed_since > CONTEXT_WAIT_SECONDS:
                    self._try_seed(stream, force=True)
                if (
                    stream.forming_dirty
                    and now - stream.last_developing >= self.config.developing_min_interval_seconds
                ):
                    self._developing(stream, now)

    def _developing(self, stream: _Stream, now: float) -> None:
        stream.forming_dirty = False
        analyzer = self.analysis.analyzer(stream.key)
        forming = self.analysis.forming(stream.key)
        if analyzer is None or forming is None:
            return
        ev = evaluate_developing(
            self.engine,
            analyzer,
            forming,
            self.analysis.context_frames(stream.key),
            market_stale=self._stale(stream.key),
        )
        previous = stream.developing
        changed = (previous is None) != (ev is None) or (
            previous is not None
            and (previous.signal_class, round(previous.score)) != (ev.signal_class, round(ev.score))
        )
        stream.developing = ev
        if changed or ev.signal_class.value != "NEUTRAL":
            stream.last_developing = now
            self.stats["developing_sent"] += 1
            self._publish(
                stream, EventType.SIGNAL_DEVELOPING, {"evaluation": evaluation_payload(ev)}
            )

    # --- publishing / persistence ----------------------------------------------------------------
    def _sink(self, key: AppKey):  # type: ignore[no-untyped-def]
        def sink(kind: str, signal: Signal) -> None:
            stream = self.streams.get(key)
            if stream is None:
                return
            if kind == "confirmed":
                self.stats["confirmed"] += 1
                stream.last_confirmed = signal
                logger.info(
                    "signals.confirmed",
                    extra={
                        "fields": {
                            "id": signal.id,
                            "class": signal.signal_class.value,
                            "score": signal.score,
                        }
                    },
                )
            stream.recent = [signal, *[s for s in stream.recent if s.id != signal.id]][:20]
            event = {
                "confirmed": EventType.SIGNAL_CONFIRMED,
                "updated": EventType.SIGNAL_UPDATED,
                "closed": EventType.SIGNAL_CLOSED,
            }[kind]
            self._publish(stream, event, {"signal": signal_payload(signal)})
            if self.database is not None:
                self._spawn(self._persist(signal))

        return sink

    def _publish(self, stream: _Stream, event: EventType, data: dict[str, Any]) -> None:
        consumers = self.analysis.consumers(stream.key)
        if consumers:
            payload = {"symbol": stream.key[0], "timeframe": stream.key[1].value, **data}
            self.market.publisher.send_to(consumers, EventEnvelope.of(event, payload))

    def _state_event(self, stream: _Stream) -> EventEnvelope:
        return EventEnvelope.of(EventType.SIGNAL_UPDATED, self.state(stream.key))

    def state(self, key: AppKey) -> dict[str, Any]:
        stream = self.streams.get(key)
        return {
            "symbol": key[0],
            "timeframe": key[1].value,
            "evaluation": evaluation_payload(stream.current) if stream and stream.current else None,
            "developing": evaluation_payload(stream.developing)
            if stream and stream.developing
            else None,
            "active": signal_payload(stream.tracker.active)
            if stream and stream.tracker.active
            else None,
            "last_confirmed": signal_payload(stream.last_confirmed)
            if stream and stream.last_confirmed
            else None,
        }

    async def _persist(self, signal: Signal) -> None:
        if self.database is None:
            return
        try:
            async with self.database.session_factory() as session:
                await signal_store.upsert_signal(session, signal, "live")
        except Exception:
            logger.exception("signals.persist_failed")

    async def _load_seen(self, stream: _Stream) -> None:
        if self.database is None:
            return
        try:
            async with self.database.session_factory() as session:
                ids = await signal_store.recent_signal_ids(
                    session, stream.key[0], stream.key[1].value
                )
            stream.tracker.remember(ids)
        except Exception:
            logger.exception("signals.load_seen_failed")

    # --- REST ---------------------------------------------------------------------------------
    async def current(self, key: AppKey) -> dict[str, Any]:
        if key in self.streams and self.streams[key].current is not None:
            return self.state(key)
        analyzer, _forming, frames = await self.analysis.on_demand(key)
        ev = evaluate_closed(self.engine, analyzer, frames)
        state = self.state(key)
        state["evaluation"] = evaluation_payload(ev)
        return state

    def health(self) -> dict[str, Any]:
        return {
            "strategy_version": self.engine.version,
            "streams": {
                _label(k): {
                    "active": s.tracker.active.id if s.tracker.active else None,
                    "suppressed": s.tracker.suppressed,
                }
                for k, s in self.streams.items()
            },
            **self.stats,
        }


def _label(key: AppKey) -> str:
    return f"{key[0]}:{key[1].value}"
