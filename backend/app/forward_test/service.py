"""Live prospective forward test of the frozen candidate (Phase 4.2).

Rules (docs/forward-testing.md):
* Only candles that OPEN at or after `started_at` and are observed CLOSING live can
  produce a signal. Seeded history is warm-up only.
* Per (symbol, timeframe) a cursor stores the last processed closed candle. After a
  restart or a feed gap, candles closed while we were not watching are used ONLY to
  advance existing open signals (their paper outcome is a fact of the market). They never
  create new signals ("no retroactive signals").
* Evaluation waits for context candles closing at the same instant (like live signals),
  requires a live, healthy, current feed and an active symbol, and uses the canonical
  MarketAnalyzer -> SignalEngine scoring/plans -> research selection -> SignalTracker.
* Confirmed terms are frozen and persisted once; lifecycle updates are forward-only.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.analysis.engine import MarketAnalyzer
from app.analysis.multi_timeframe.context import context_timeframes
from app.analysis.service import AnalysisService
from app.db.session import Database
from app.forward_test import store
from app.forward_test.candidate import (
    CRITERIA,
    DISPLAY_NAME,
    RESEARCH_VERSION,
    TIMEFRAMES,
    UNIVERSE,
    candidate,
    fingerprint,
    forward_version,
    frozen_config,
)
from app.forward_test.codec import freeze, lifecycle, thaw
from app.forward_test.evaluate import LiveContext, evaluate_candle
from app.forward_test.metrics import assess, summary
from app.market_data.engine import MarketDataEngine
from app.market_data.exceptions import MarketDataError
from app.market_data.timeframes import Timeframe
from app.signal_engine.lifecycle import SignalTracker
from app.signal_engine.models import Signal, SignalEvaluation
from app.signal_engine.serialize import evaluation_payload, signal_payload
from app.websocket.events import EventEnvelope, EventType

logger = logging.getLogger(__name__)

AppKey = tuple[str, Timeframe]
CONSUMER = "forward-test"
LOOP_INTERVAL = 1.0
CONTEXT_WAIT_SECONDS = 15.0
STALE_AFTER_CLOSE_SECONDS = 120  # a candle evaluated later than this is not "current"
RUN_POLL_SECONDS = 30.0
DISCLAIMER_AR = "الإشارات قيد الاختبار وليست توصيات مضمونة."
STATUS_AR = {
    "forward_testing": "اختبار مباشر",
    "paused": "متوقف",
    "stopped": "متوقف",
    "passed_forward_test": "اجتاز الاختبار المباشر",
    "failed_forward_test": "فشل الاختبار المباشر",
}


@dataclass(slots=True)
class _Stream:
    key: AppKey
    tracker: SignalTracker
    cursor: int | None = None  # close time (s) of the last processed closed candle
    pending_close: int | None = None
    pending_since: float = 0.0
    current: SignalEvaluation | None = None
    last_confirmed: Signal | None = None
    catchup_candles: int = 0


@dataclass(slots=True)
class _Run:
    id: int
    started_at: int  # epoch seconds
    status: str
    symbols: list[str]
    timeframes: list[str]
    unavailable: set[str] = field(default_factory=set)


class ForwardTestService:
    def __init__(
        self,
        analysis: AnalysisService,
        market: MarketDataEngine,
        database: Database | None,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.analysis = analysis
        self.market = market
        self.database = database
        self.clock = clock
        self.variant = candidate()
        self.config = frozen_config(self.variant)
        self.version = forward_version(self.config)
        self.fingerprint = fingerprint(self.version)
        self.tracker_config = self.variant.tracker_config()
        self.run: _Run | None = None
        self.streams: dict[AppKey, _Stream] = {}
        self.subscribed = False
        self.problem: str | None = None
        self.stats: dict[str, Any] = {
            "evaluations": 0,
            "confirmed": 0,
            "catchup_candles": 0,
            "persist_errors": 0,
            "last_candle_close": None,
            "last_evaluation_at": None,
            "last_persist_ok_at": None,
            "last_persist_error": None,
            "last_persist_error_at": None,
        }
        self._queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self._tasks: list[asyncio.Task[Any]] = []
        self._last_poll = 0.0
        self._last_checkpoint_day: str | None = None
        analysis.listeners.append(self)

    # --- lifecycle ------------------------------------------------------------------------
    async def start(self, *, background_loop: bool = True) -> None:
        """`background_loop=False` (tests) runs only the persistence writer; the caller then
        drives load/seed/close/checkpoint explicitly."""
        self._tasks = [asyncio.create_task(self._writer(), name="forward-test-writer")]
        if background_loop:
            self._tasks.append(asyncio.create_task(self._loop(), name="forward-test-loop"))

    async def stop(self) -> None:
        await self.flush()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def flush(self) -> None:
        """Wait until every queued write has been attempted."""
        if self._tasks and not self._tasks[0].done():
            await self._queue.join()

    # --- run loading / restoration -------------------------------------------------------
    async def load(self) -> bool:
        """Load the open run for THIS frozen version and restore its state."""
        if self.database is None:
            return False
        async with self.database.session_factory() as session:
            other = await store.open_run(session)
            if other is not None and other.strategy_version != self.version:
                self.problem = (
                    f"open run {other.id} uses {other.strategy_version}, code is {self.version}: "
                    "the frozen strategy changed; start a NEW run for the new version"
                )
                logger.error("forward_test.version_mismatch", extra={"fields": {"run": other.id}})
                return False
            row = await store.open_run(session, self.version)
            if row is None:
                return False
            signals = await store.load_signals(session, row.id)
            cursors = await store.cursors(session, row.id)
        self.problem = None
        self.run = _Run(
            id=row.id,
            started_at=int(row.started_at.timestamp()),
            status=row.status,
            symbols=list(row.symbols),
            timeframes=list(row.timeframes),
        )
        self.streams = {}
        for symbol in self.run.symbols:
            for tf in self.run.timeframes:
                key = (symbol, Timeframe(tf))
                tracker = SignalTracker(
                    symbol,
                    tf,
                    self.tracker_config,
                    step_seconds=Timeframe(tf).seconds,
                    sink=self._sink(key),
                )
                mine = [s for s in signals if s.symbol == symbol and s.timeframe == tf]
                tracker.restore(mine)
                stream = _Stream(key, tracker, cursor=cursors.get((symbol, tf)))
                stream.last_confirmed = mine[-1] if mine else None
                self.streams[key] = stream
        logger.info(
            "forward_test.loaded",
            extra={"fields": {"run": row.id, "signals": len(signals), "status": row.status}},
        )
        return True

    async def _subscribe_all(self) -> None:
        if self.run is None:
            return
        for key in list(self.streams):
            symbol, tf = key
            try:
                await self.market.subscribe(CONSUMER, symbol, tf)
                await self.analysis.subscribe(CONSUMER, symbol, tf)
            except MarketDataError as exc:
                self.run.unavailable.add(symbol)
                logger.warning(
                    "forward_test.symbol_unavailable",
                    extra={"fields": {"symbol": symbol, "error": str(exc)}},
                )
        self.subscribed = True

    async def _unsubscribe_all(self) -> None:
        for symbol, tf in list(self.streams):
            with contextlib.suppress(Exception):
                await self.analysis.unsubscribe(CONSUMER, symbol, tf)
                await self.market.unsubscribe(CONSUMER, symbol, tf)
        self.subscribed = False

    # --- ownership (which streams show forward-test signals) --------------------------------
    def owns(self, key: AppKey) -> bool:
        return self.run is not None and key in self.streams

    def active(self) -> bool:
        return self.run is not None and self.run.status in store.ACTIVE_STATUSES

    # --- AnalysisListener ---------------------------------------------------------------------
    def on_seeded(self, key: AppKey, analyzer: MarketAnalyzer) -> None:
        stream = self.streams.get(key)
        if stream is None or not self.active() or not len(analyzer.series):
            return
        bars = analyzer.series.tail(len(analyzer.series))
        last = bars[-1].close_time
        if stream.cursor is None:
            stream.cursor = last  # first sight: everything seeded is warm-up only
        else:
            # Candles closed while we were not watching: advance open signals only.
            for bar in bars:
                if bar.close_time > stream.cursor:
                    stream.tracker.on_bar(bar)
                    stream.catchup_candles += 1
                    self.stats["catchup_candles"] += 1
            stream.cursor = max(stream.cursor, last)
        stream.pending_close = None
        self._queue.put_nowait(("cursor", {(key[0], key[1].value): stream.cursor}))

    def on_closed(self, key: AppKey, analyzer: MarketAnalyzer) -> None:
        stream = self.streams.get(key)
        if stream is not None and self.active():
            bar = analyzer.series.last
            if stream.cursor is None or bar.close_time > stream.cursor:
                stream.tracker.on_bar(bar)  # lifecycle first, exactly like the replay
                stream.cursor = bar.close_time
                self.stats["last_candle_close"] = bar.close_time
                self._queue.put_nowait(("cursor", {(key[0], key[1].value): bar.close_time}))
                if (
                    self.run is not None
                    and self.run.status == "forward_testing"  # paused: lifecycle only
                    and bar.time >= self.run.started_at  # forward boundary (open time)
                ):
                    stream.pending_close = bar.close_time
                    stream.pending_since = time.monotonic()
                    self._try_evaluate(stream)
        for other in list(self.streams.values()):
            if (
                other.pending_close is not None
                and other.key[0] == key[0]
                and key[1] in context_timeframes(other.key[1])
            ):
                self._try_evaluate(other)

    def on_forming(self, key: AppKey) -> None:  # developing hypotheses are not forward-tested
        return

    # --- evaluation ------------------------------------------------------------------------------
    def _context_ready(self, stream: _Stream) -> bool:
        close = stream.pending_close
        if close is None:
            return False
        for ctf in context_timeframes(stream.key[1]):
            if close % ctf.seconds:
                continue
            ctx = self.analysis.analyzer((stream.key[0], ctf))
            if ctx is None or not len(ctx.series):
                continue
            if ctx.series.last.close_time < close:
                return False
        return True

    def _live_context(self, key: AppKey, close_time: int) -> LiveContext:
        stale = self.market.stream_state(key) != "live"
        stale = stale or self.market.health.overall == "disconnected"
        stale = stale or self.clock() - close_time > STALE_AFTER_CLOSE_SECONDS
        try:
            active = self.market.symbols.get(key[0]).is_active
        except MarketDataError:
            active = False
        return LiveContext(market_stale=stale, symbol_active=active)

    def _try_evaluate(self, stream: _Stream, *, force: bool = False) -> None:
        if stream.pending_close is None:
            return
        if not force and not self._context_ready(stream):
            return
        analyzer = self.analysis.analyzer(stream.key)
        close = stream.pending_close
        stream.pending_close = None
        if analyzer is None or analyzer.series.last.close_time != close:
            return
        ev = evaluate_candle(
            self.variant,
            analyzer,
            self.analysis.context_frames(stream.key),
            self._live_context(stream.key, close),
            strategy_version=self.version,
        )
        self.stats["evaluations"] += 1
        self.stats["last_evaluation_at"] = int(self.clock())
        stream.current = ev
        stream.tracker.on_evaluation(ev, analyzer.series.last)
        # observability only (not part of the frozen strategy)
        logger.info(
            "forward_test.evaluated",
            extra={
                "fields": {
                    "symbol": stream.key[0],
                    "timeframe": stream.key[1].value,
                    "close": close,
                    "class": ev.signal_class.value,
                    "score": round(ev.score, 1),
                    "reason": ev.neutral_reason,
                }
            },
        )
        self._publish(stream.key, EventType.SIGNAL_UPDATED, {"evaluation": evaluation_payload(ev)})

    # --- signal events ----------------------------------------------------------------------------
    def _sink(self, key: AppKey) -> Callable[[str, Signal], None]:
        def sink(kind: str, signal: Signal) -> None:
            stream = self.streams.get(key)
            if kind == "confirmed":
                self.stats["confirmed"] += 1
                if stream is not None:
                    stream.last_confirmed = signal
            self._persist(signal)
            event = {
                "confirmed": EventType.SIGNAL_CONFIRMED,
                "updated": EventType.SIGNAL_UPDATED,
                "closed": EventType.SIGNAL_CLOSED,
            }[kind]
            self._publish(key, event, {"signal": signal_payload(signal)})

        return sink

    def _persist(self, signal: Signal) -> None:
        # snapshot NOW: the live object keeps changing after this event
        self._queue.put_nowait(("signal", thaw(freeze(signal), lifecycle(signal))))

    async def _writer(self) -> None:
        while True:
            kind, payload = await self._queue.get()
            try:
                if self.run is None or self.database is None:
                    continue
                async with self.database.session_factory() as session:
                    if kind == "signal":
                        await store.save_signal(session, self.run.id, payload, self.tracker_config)
                    elif kind == "cursor":
                        await store.save_cursors(session, self.run.id, payload)
                self.stats["last_persist_ok_at"] = int(self.clock())
            except Exception as exc:
                self.stats["persist_errors"] += 1
                self.stats["last_persist_error"] = repr(exc)[:300]
                self.stats["last_persist_error_at"] = int(self.clock())
                logger.exception("forward_test.persist_failed")
            finally:
                self._queue.task_done()

    # --- loop: run pickup, subscriptions, context timeouts, checkpoints -------------------------
    async def _loop(self) -> None:
        while True:
            try:
                await self._tick()
            except Exception:
                logger.exception("forward_test.tick_failed")
            await asyncio.sleep(LOOP_INTERVAL)

    async def _tick(self) -> None:
        mono = time.monotonic()
        if (self.run is None or not self.active()) and mono - self._last_poll >= RUN_POLL_SECONDS:
            self._last_poll = mono
            await self.load()
        if self.run is None or not self.active():
            return
        if not self.subscribed and self.market.symbols.loaded:
            await self._subscribe_all()
        for stream in self.streams.values():
            if (
                stream.pending_close is not None
                and mono - stream.pending_since > CONTEXT_WAIT_SECONDS
            ):
                self._try_evaluate(stream, force=True)
        day = datetime.fromtimestamp(self.clock(), tz=UTC).date().isoformat()
        if day != self._last_checkpoint_day:
            await self.checkpoint()

    async def checkpoint(self) -> dict[str, Any] | None:
        """Daily metrics snapshot + conservative automatic PASS/FAIL conclusion."""
        if self.run is None or self.database is None:
            return None
        await self.flush()
        now = self.clock()
        day = datetime.fromtimestamp(now, tz=UTC).date()
        async with self.database.session_factory() as session:
            signals = await store.load_signals(session, self.run.id)
            elapsed = (now - self.run.started_at) / 86400
            metrics = summary(signals, CRITERIA)
            verdict = assess(signals, elapsed, CRITERIA)
            metrics["assessment"] = {"verdict": verdict.verdict, "reasons": list(verdict.reasons)}
            metrics["elapsed_days"] = round(elapsed, 2)
            await store.save_checkpoint(session, self.run.id, day, metrics)
        self._last_checkpoint_day = day.isoformat()
        if self.run.status == "forward_testing" and verdict.verdict in (
            "PASS_CRITERIA_MET",
            "FAIL_CRITERIA_MET",
        ):
            status = (
                "passed_forward_test"
                if verdict.verdict == "PASS_CRITERIA_MET"
                else "failed_forward_test"
            )
            await self.set_status(status, "; ".join(verdict.reasons) or "all pass criteria met")
        return metrics

    # --- admin controls ---------------------------------------------------------------------------
    async def set_status(self, status: str, note: str) -> dict[str, Any]:
        if self.run is None or self.database is None:
            raise LookupError("no_active_forward_test_run")
        now = datetime.fromtimestamp(self.clock(), tz=UTC)
        if status not in store.ACTIVE_STATUSES:
            await self._close_open_signals()
        async with self.database.session_factory() as session:
            row = await store.set_status(session, self.run.id, status, note, now)
            payload = store.run_payload(row)
        self.run.status = status
        if status not in store.ACTIVE_STATUSES:
            await self._unsubscribe_all()
            await self.flush()
        for key in self.streams:
            self._publish(key, EventType.SIGNAL_UPDATED, self.state(key))
        return payload

    async def _close_open_signals(self) -> None:
        """Run stop/conclusion: open signals end as END_OF_DATA (never counted as trades)."""
        for stream in self.streams.values():
            tracker = stream.tracker
            signal = tracker.active
            if signal is None:
                continue
            analyzer = self.analysis.analyzer(stream.key)
            last = analyzer.series.last if analyzer is not None and len(analyzer.series) else None
            when = last.close_time if last else int(self.clock())
            price = last.close if last else signal.plan.preferred_entry
            tracker.finish_open(when, price)
            self._persist(signal)
        await self.flush()

    # --- UI ---------------------------------------------------------------------------------------
    def info(self, timeframe: str) -> dict[str, Any]:
        status = self.run.status if self.run else "stopped"
        return {
            "version": self.version,
            "fingerprint": self.fingerprint,
            "name": DISPLAY_NAME,
            "status": status,
            "status_ar": STATUS_AR.get(status, status),
            "label_ar": "اختبار مباشر",
            "forward_test": status == "forward_testing",
            "signal_capable": status == "forward_testing" and timeframe in TIMEFRAMES,
            "score_calibrated": False,
            "note_ar": DISCLAIMER_AR,
            "scope_note_ar": None,
        }

    def state(self, key: AppKey) -> dict[str, Any]:
        stream = self.streams.get(key)
        tracker = stream.tracker if stream else None
        return {
            "symbol": key[0],
            "timeframe": key[1].value,
            "strategy": self.info(key[1].value),
            "evaluation": evaluation_payload(stream.current) if stream and stream.current else None,
            "developing": None,
            "active": signal_payload(tracker.active) if tracker and tracker.active else None,
            "last_confirmed": signal_payload(stream.last_confirmed)
            if stream and stream.last_confirmed
            else None,
        }

    def subscribe(self, consumer: str, key: AppKey) -> None:
        self.market.publisher.send_to(
            [consumer], EventEnvelope.of(EventType.SIGNAL_UPDATED, self.state(key))
        )

    def _publish(self, key: AppKey, event: EventType, data: dict[str, Any]) -> None:
        consumers = self.analysis.consumers(key) - {CONSUMER}
        if consumers:
            payload = {
                "symbol": key[0],
                "timeframe": key[1].value,
                "strategy": self.info(key[1].value),
                **data,
            }
            self.market.publisher.send_to(consumers, EventEnvelope.of(event, payload))

    def health(self) -> dict[str, Any]:
        if self.problem:
            state = "degraded"
        elif self.run is None or self.run.status not in store.ACTIVE_STATUSES:
            state = "stopped"
        elif self.run.status == "paused":
            state = "paused"
        elif (
            (self.stats["last_persist_error_at"] or 0) > (self.stats["last_persist_ok_at"] or 0)
            or self.market.health.overall == "disconnected"
            or self.run.unavailable
        ):
            state = "degraded"
        else:
            state = "running"
        return {
            "state": state,
            "problem": self.problem,
            "version": self.version,
            "fingerprint": self.fingerprint,
            "research_version": RESEARCH_VERSION,
            "run_id": self.run.id if self.run else None,
            "status": self.run.status if self.run else None,
            "started_at": self.run.started_at if self.run else None,
            "subscribed": self.subscribed,
            "unavailable_symbols": sorted(self.run.unavailable) if self.run else [],
            "streams": len(self.streams),
            "universe": list(UNIVERSE),
            "timeframes": list(TIMEFRAMES),
            **self.stats,
        }
