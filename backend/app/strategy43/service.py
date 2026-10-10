"""Live Strategy 4.3 engine + market-wide opportunity scanner (v1.2).

Always on: started with the application in every runtime mode, independent of the
Strategy 4.2 forward-test run status (the cause of «متابعة الإشارات غير نشطة حالياً»).

* Universe: the liquid core (Phase 4.1 methodology) + the most liquid active USDT
  perpetuals by 24h traded value, subscribed on 15m / 30m / 1h at startup. Any other
  symbol the user opens on a primary timeframe is added on demand.
* Closed candles only, canonical pipeline (`forward_test.evaluate.evaluate_candle`):
  MarketAnalyzer snapshot + context frames closed at the same instant -> SignalEngine
  weighted evidence -> 4.3 selection -> SignalTracker lifecycle.
* No retroactive signals: only candles observed closing live (and recent) can confirm a
  signal. After a restart, candles closed while the app was down (per-stream cursor) only
  advance open signals.
* Every confirmed signal is persisted once (frozen terms) and is the canonical object for
  the chart, the scanner, the execution layer and Telegram.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.analysis.engine import MarketAnalyzer
from app.analysis.multi_timeframe.context import context_timeframes
from app.analysis.service import AnalysisService
from app.db.session import Database
from app.forward_test.codec import freeze, lifecycle, thaw
from app.forward_test.evaluate import LiveContext, evaluate_candle
from app.market_data.engine import MarketDataEngine
from app.market_data.exceptions import MarketDataError
from app.market_data.timeframes import Timeframe
from app.signal_engine.enums import SignalState
from app.signal_engine.lifecycle import SignalTracker
from app.signal_engine.models import Signal, SignalEvaluation
from app.signal_engine.serialize import evaluation_payload, signal_payload
from app.strategy43 import store
from app.strategy43.config import (
    CORE_UNIVERSE,
    FAMILY_AR,
    NAME,
    REGIME_43,
    REGIME_AR,
    SCANNER_SIZE,
    TIER_AR,
    TIER_RANK,
    TIMEFRAMES,
    fingerprint,
    strategy_version,
    tier,
    variant,
)
from app.telegram.models import SignalAlert
from app.websocket.events import EventEnvelope, EventType

logger = logging.getLogger(__name__)

AppKey = tuple[str, Timeframe]
CONSUMER = "strategy-4.3"
LOOP_INTERVAL = 1.0
CONTEXT_WAIT_SECONDS = 15.0
STALE_AFTER_CLOSE_SECONDS = 120
SUBSCRIBE_SPACING = 0.15  # gentle REST seeding at startup
MAX_ON_DEMAND = 60
OPEN_STATES = frozenset(
    {SignalState.CONFIRMED, SignalState.ACTIVE, SignalState.TP1_HIT, SignalState.TP2_HIT}
)
NOTE_AR = "تحليل وليس نصيحة مالية. قوة الإشارة مقياس لتوافق الأدلة من 100 وليست احتمال ربح."
STATE_AR = {
    "confirmed": "بانتظار الدخول",
    "active": "صفقة نشطة",
    "tp1_hit": "تحقق الهدف 1",
    "tp2_hit": "تحقق الهدف 2",
    "tp3_hit": "تحقق الهدف 3",
    "stopped": "ضُرب وقف الخسارة",
    "invalidated": "فاتت منطقة الدخول",
    "expired": "انتهت الصلاحية",
    "closed": "مغلقة",
}

AlertSink = Callable[[SignalAlert], None]


@dataclass(slots=True)
class _Stream:
    key: AppKey
    tracker: SignalTracker
    cursor: int | None = None
    pending_close: int | None = None
    pending_since: float = 0.0
    current: SignalEvaluation | None = None
    last_confirmed: Signal | None = None
    evaluated_at: int | None = None
    on_demand: bool = False


def _side(signal: Signal) -> int:
    return 1 if signal.side.value == "long" else -1


class Strategy43Service:
    def __init__(
        self,
        analysis: AnalysisService,
        market: MarketDataEngine,
        database: Database | None,
        *,
        alerts: AlertSink | None = None,
        scanner_size: int = SCANNER_SIZE,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.analysis = analysis
        self.market = market
        self.database = database
        self.alerts = alerts
        self.scanner_size = scanner_size
        self.clock = clock
        self.name = NAME
        self.variant = variant()
        self.version = strategy_version()
        self.fingerprint = fingerprint(self.version)
        self.tracker_config = self.variant.tracker_config()
        self.streams: dict[AppKey, _Stream] = {}
        self.universe: list[str] = []
        self.unavailable: set[str] = set()
        self.ready = False  # universe built + open signals restored
        self.subscribed = 0
        self.problem: str | None = None
        self.started_at: int | None = None
        self.stats: dict[str, Any] = {
            "evaluations": 0,
            "confirmed": 0,
            "catchup_candles": 0,
            "persist_errors": 0,
            "last_candle_close": None,  # آخر شمعة تم تحليلها
            "last_market_update": None,  # آخر تحديث للسوق
            "last_scan_at": None,  # آخر فحص للفرص
            "last_signal_at": None,  # آخر إشارة
            "last_persist_error": None,
        }
        self._restored: dict[tuple[str, str], list[Signal]] = {}
        self._cursors: dict[tuple[str, str], int] = {}
        self._notified: dict[str, int] = {}  # signal id -> targets already alerted
        self._queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        self._tasks: list[asyncio.Task[Any]] = []
        self._pending_subs: set[AppKey] = set()
        self.subscribe_errors: dict[AppKey, str] = {}
        analysis.listeners.append(self)

    # --- lifecycle --------------------------------------------------------------------------
    async def start(self, *, background_loop: bool = True) -> None:
        self.started_at = int(self.clock())
        self._tasks = [asyncio.create_task(self._writer(), name="strategy43-writer")]
        if background_loop:
            self._tasks.append(asyncio.create_task(self._boot(), name="strategy43-boot"))
            self._tasks.append(asyncio.create_task(self._loop(), name="strategy43-loop"))

    async def stop(self) -> None:
        await self.flush()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks = []

    async def flush(self) -> None:
        if self._tasks and not self._tasks[0].done():
            await self._queue.join()

    async def _boot(self) -> None:
        """Wait for the symbol list, restore state, build the universe, subscribe."""
        while not self.market.symbols.loaded:  # noqa: ASYNC110 - polled, no event exposed
            await asyncio.sleep(0.5)
        try:
            await self.restore()
        except Exception as exc:
            self.problem = f"تعذر استعادة الإشارات المحفوظة: {exc!r}"[:300]
            logger.exception("strategy43.restore_failed")
        self.universe = await self.build_universe()
        for symbol in self.universe:
            for tf in TIMEFRAMES:
                self._ensure(symbol, Timeframe(tf))
        self.ready = True
        for symbol in self.universe:
            for tf in TIMEFRAMES:
                await self._subscribe((symbol, Timeframe(tf)))
                await asyncio.sleep(SUBSCRIBE_SPACING)
        logger.info(
            "strategy43.started",
            extra={"fields": {"universe": len(self.universe), "streams": len(self.streams)}},
        )

    async def build_universe(self) -> list[str]:
        def active(symbol: str) -> bool:
            # same methodology as the research universe: live crypto USDT perpetuals only
            try:
                info = self.market.symbols.get(symbol)
            except MarketDataError:
                return False
            return info.is_active and info.is_crypto

        core = [s for s in CORE_UNIVERSE if active(s)]
        ranked: list[tuple[float, str]] = []
        try:
            tickers = await self.market.tickers.tickers()
            for t in tickers.values():
                if t.symbol in core or not t.symbol.endswith("USDT") or not active(t.symbol):
                    continue
                ranked.append((float(t.volume_24h) * float(t.last_price), t.symbol))
        except Exception as exc:  # the core universe still works without tickers
            self.problem = f"تعذر جلب قائمة السيولة: {exc!r}"[:300]
            logger.warning("strategy43.tickers_failed", extra={"fields": {"error": repr(exc)}})
        ranked.sort(reverse=True)
        extra = [s for _, s in ranked[: max(0, self.scanner_size - len(core))]]
        return core + extra

    async def restore(self) -> None:
        if self.database is None:
            return
        async with self.database.session_factory() as session:
            signals = await store.open_signals(session, self.version)
            self._cursors = await store.cursors(session)
            last = await store.last_signal_time(session)
        self.stats["last_signal_at"] = last
        self._restored = {}
        for s in signals:
            self._restored.setdefault((s.symbol, s.timeframe), []).append(s)
            self._notified[s.id] = s.targets_hit
        for symbol, tf in list(self._restored):
            self._ensure(symbol, Timeframe(tf))

    def _ensure(self, symbol: str, tf: Timeframe, *, on_demand: bool = False) -> _Stream:
        key = (symbol, tf)
        stream = self.streams.get(key)
        if stream is None:
            tracker = SignalTracker(
                symbol, tf.value, self.tracker_config, step_seconds=tf.seconds, sink=self._sink(key)
            )
            mine = self._restored.pop((symbol, tf.value), [])
            if mine:
                tracker.restore(mine)
            stream = _Stream(key, tracker, cursor=self._cursors.get((symbol, tf.value)))
            stream.last_confirmed = mine[-1] if mine else None
            stream.on_demand = on_demand
            self.streams[key] = stream
        return stream

    async def _subscribe(self, key: AppKey) -> None:
        symbol, tf = key
        try:
            await self.market.subscribe(CONSUMER, symbol, tf)
            await self.analysis.subscribe(CONSUMER, symbol, tf)
            self.subscribed += 1
        except MarketDataError as exc:
            self.unavailable.add(symbol)
            logger.warning(
                "strategy43.symbol_unavailable",
                extra={"fields": {"symbol": symbol, "error": str(exc)}},
            )
        except Exception as exc:
            self.subscribe_errors[key] = repr(exc)[:200]
            logger.exception("strategy43.subscribe_failed")
        finally:
            self._pending_subs.discard(key)

    # --- ownership: 4.3 owns every primary-timeframe stream ---------------------------------
    def owns(self, key: AppKey) -> bool:
        return key[1].value in TIMEFRAMES

    def watch(self, key: AppKey) -> None:
        """A chart opened this stream: evaluate it live from now on (on-demand symbols)."""
        if not self.owns(key) or key in self.streams or key in self._pending_subs:
            return
        if sum(1 for s in self.streams.values() if s.on_demand) >= MAX_ON_DEMAND * 3:
            return
        symbol = key[0]
        for tf in TIMEFRAMES:  # all three primary timeframes: best-opportunity fallback
            k = (symbol, Timeframe(tf))
            if k not in self.streams:
                self._ensure(symbol, Timeframe(tf), on_demand=True)
                self._pending_subs.add(k)
                self._tasks.append(asyncio.ensure_future(self._subscribe(k)))

    # --- AnalysisListener -------------------------------------------------------------------
    def on_seeded(self, key: AppKey, analyzer: MarketAnalyzer) -> None:
        stream = self.streams.get(key)
        if stream is None or not len(analyzer.series):
            return
        bars = analyzer.series.tail(len(analyzer.series))
        last = bars[-1].close_time
        if stream.cursor is None:
            stream.cursor = last  # first sight: seeded history is warm-up only
        else:
            for bar in bars:  # closed while we were not watching: lifecycle only
                if bar.close_time > stream.cursor:
                    stream.tracker.on_bar(bar)
                    self.stats["catchup_candles"] += 1
            stream.cursor = max(stream.cursor, last)
        stream.pending_close = None
        self._queue.put_nowait(("cursor", {(key[0], key[1].value): stream.cursor}))

    def on_closed(self, key: AppKey, analyzer: MarketAnalyzer) -> None:
        now = int(self.clock())
        self.stats["last_market_update"] = now
        stream = self.streams.get(key)
        if stream is not None:
            bar = analyzer.series.last
            if stream.cursor is None or bar.close_time > stream.cursor:
                stream.tracker.on_bar(bar)  # lifecycle first, exactly like the replay
                stream.cursor = bar.close_time
                self.stats["last_candle_close"] = bar.close_time
                self._queue.put_nowait(("cursor", {(key[0], key[1].value): bar.close_time}))
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

    def on_forming(self, key: AppKey) -> None:
        return

    # --- evaluation ---------------------------------------------------------------------------
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
        try:
            ev = evaluate_candle(
                self.variant,
                analyzer,
                self.analysis.context_frames(stream.key),
                self._live_context(stream.key, close),
                strategy_version=self.version,
            )
        except Exception:
            logger.exception("strategy43.evaluate_failed")
            return
        now = int(self.clock())
        self.stats["evaluations"] += 1
        self.stats["last_scan_at"] = now
        stream.evaluated_at = now
        stream.current = ev
        stream.tracker.on_evaluation(ev, analyzer.series.last)
        self._publish(stream.key, EventType.SIGNAL_UPDATED, {"evaluation": self._ev_payload(ev)})

    # --- signal events ------------------------------------------------------------------------
    def _sink(self, key: AppKey) -> Callable[[str, Signal], None]:
        def sink(kind: str, signal: Signal) -> None:
            stream = self.streams.get(key)
            if kind == "confirmed":
                self.stats["confirmed"] += 1
                self.stats["last_signal_at"] = signal.confirmed_time
                if stream is not None:
                    stream.last_confirmed = signal
            self._persist(signal)
            self._alert(kind, signal)
            event = {
                "confirmed": EventType.SIGNAL_CONFIRMED,
                "updated": EventType.SIGNAL_UPDATED,
                "closed": EventType.SIGNAL_CLOSED,
            }[kind]
            self._publish(key, event, {"signal": self.signal_view(signal)})

        return sink

    def valid_until(self, signal: Signal) -> int:
        step = Timeframe(signal.timeframe).seconds
        return signal.confirmed_time + self.tracker_config.entry_expiry_bars * step

    def _persist(self, signal: Signal) -> None:
        # snapshot NOW: the live object keeps changing after this event
        self._queue.put_nowait(("signal", thaw(freeze(signal), lifecycle(signal))))

    async def _writer(self) -> None:
        while True:
            kind, payload = await self._queue.get()
            try:
                if self.database is None:
                    continue
                async with self.database.session_factory() as session:
                    if kind == "signal":
                        await store.save_signal(session, payload, self.valid_until(payload))
                    elif kind == "cursor":
                        await store.save_cursors(session, payload)
            except Exception as exc:
                self.stats["persist_errors"] += 1
                self.stats["last_persist_error"] = repr(exc)[:300]
                logger.exception("strategy43.persist_failed")
            finally:
                self._queue.task_done()

    # --- Telegram ------------------------------------------------------------------------------
    def alert_for(self, signal: Signal, event: str) -> SignalAlert:
        plan = signal.plan
        targets = tuple(t.price for t in plan.targets)
        rr = tuple(float(t.rr) for t in plan.targets)
        precision = None
        with contextlib.suppress(Exception):
            precision = self.market.symbols.get(signal.symbol).price_precision
        return SignalAlert(
            signal_id=signal.id,
            event=event,
            symbol=signal.symbol,
            side=_side(signal),
            timeframe=signal.timeframe,
            primary_timeframe=signal.timeframe,
            execution_timeframe=None,
            entry=plan.preferred_entry,
            stop=plan.stop,
            targets=(targets[0], targets[1], targets[2]),
            rr=(rr[0], rr[1], rr[2]),
            tier=tier(signal.score),
            score=signal.score,
            timing_score=None,
            family_ar=FAMILY_AR.get(signal.family.value, signal.family.value),
            signal_time=signal.confirmed_time,
            price_precision=precision,
        )

    def _alert(self, kind: str, signal: Signal) -> None:
        if self.alerts is None:
            return
        events: list[str] = []
        if kind == "confirmed":
            events.append("NEW")
            self._notified[signal.id] = 0
        prev = self._notified.get(signal.id, 0)
        for n in range(prev + 1, min(signal.targets_hit, 3) + 1):
            events.append(f"TP{n}")
        self._notified[signal.id] = max(prev, signal.targets_hit)
        if kind == "closed":
            if signal.state is SignalState.STOPPED:
                events.append("STOPPED")
            elif signal.state in (SignalState.EXPIRED, SignalState.INVALIDATED):
                events.append("EXPIRED")
            self._notified.pop(signal.id, None)
        for event in events:
            try:
                self.alerts(self.alert_for(signal, event))
            except Exception:  # Telegram can never break the engine
                logger.exception("strategy43.alert_failed")

    # --- views -----------------------------------------------------------------------------------
    def info(self, timeframe: str) -> dict[str, Any]:
        capable = timeframe in TIMEFRAMES
        return {
            "version": self.version,
            "fingerprint": self.fingerprint,
            "name": NAME,
            "status": "live" if self.ready else "starting",
            "status_ar": "نشط" if self.ready else "قيد التشغيل",
            "label_ar": "Strategy 4.3",
            "forward_test": False,
            "signal_capable": capable,
            "score_calibrated": False,
            "note_ar": NOTE_AR,
            "scope_note_ar": None,
        }

    def signal_view(self, signal: Signal) -> dict[str, Any]:
        t = tier(signal.score)
        return {
            **signal_payload(signal),
            "tier": t,
            "tier_ar": TIER_AR[t],
            "family_ar": FAMILY_AR.get(signal.family.value, signal.family.value),
            "state_ar": STATE_AR.get(signal.state.value, signal.state.value),
            "valid_until": self.valid_until(signal),
            "regime_43": REGIME_43.get(signal.regime or "", "TRANSITION"),
        }

    def _ev_payload(self, ev: SignalEvaluation) -> dict[str, Any]:
        out = evaluation_payload(ev)
        t = tier(ev.score) if ev.is_trade else "WAIT"
        out["tier"] = t
        out["tier_ar"] = TIER_AR[t]
        return out

    def state(self, key: AppKey) -> dict[str, Any]:
        stream = self.streams.get(key)
        tracker = stream.tracker if stream else None
        return {
            "symbol": key[0],
            "timeframe": key[1].value,
            "strategy": self.info(key[1].value),
            "evaluation": self._ev_payload(stream.current) if stream and stream.current else None,
            "developing": None,
            "active": self.signal_view(tracker.active) if tracker and tracker.active else None,
            "last_confirmed": self.signal_view(stream.last_confirmed)
            if stream and stream.last_confirmed
            else None,
            "best": self.best_for_symbol(key[0]),
            "evaluated_at": stream.evaluated_at if stream else None,
            "watching": stream is not None,
        }

    def subscribe(self, consumer: str, key: AppKey) -> None:
        self.watch(key)
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
                "best": self.best_for_symbol(key[0]),
                **data,
            }
            self.market.publisher.send_to(consumers, EventEnvelope.of(event, payload))

    # --- scanner ----------------------------------------------------------------------------------
    def open_signals(self) -> list[Signal]:
        return [
            s.tracker.active
            for s in self.streams.values()
            if s.tracker.active is not None and s.tracker.active.state in OPEN_STATES
        ]

    def opportunity(self, signal: Signal) -> dict[str, Any]:
        t = tier(signal.score)
        plan = signal.plan
        return {
            "id": signal.id,
            "symbol": signal.symbol,
            "timeframe": signal.timeframe,
            "side": "BUY" if _side(signal) == 1 else "SELL",
            "tier": t,
            "tier_ar": TIER_AR[t],
            "score": round(signal.score, 1),
            "family": signal.family.value,
            "family_ar": FAMILY_AR.get(signal.family.value, signal.family.value),
            "state": signal.state.value,
            "state_ar": STATE_AR.get(signal.state.value, signal.state.value),
            "entry": plan.preferred_entry,
            "stop": plan.stop,
            "targets": [t.price for t in plan.targets],
            "rr": [float(t.rr) for t in plan.targets],
            "confirmed_time": signal.confirmed_time,
            "valid_until": self.valid_until(signal),
            "regime": REGIME_43.get(signal.regime or "", "TRANSITION"),
            "regime_ar": REGIME_AR.get(REGIME_43.get(signal.regime or "", "TRANSITION"), ""),
        }

    @staticmethod
    def _rank(signal: Signal, now: float) -> tuple[float, ...]:
        fresh = (
            1.0 if signal.state is SignalState.CONFIRMED else 0.6
        )  # waiting for entry first, then entered before targets
        age_h = max(0.0, now - signal.confirmed_time) / 3600
        rr2 = float(signal.plan.targets[1].rr)
        return (
            TIER_RANK[tier(signal.score)],
            fresh,
            round(signal.score, 0),
            -round(age_h, 1),
            rr2,
        )

    def opportunities(self, limit: int = 20) -> list[dict[str, Any]]:
        """«أفضل الفرص الآن»: open confirmed 4.3 signals, best first."""
        now = self.clock()
        ranked = sorted(self.open_signals(), key=lambda s: self._rank(s, now), reverse=True)
        return [self.opportunity(s) for s in ranked[:limit]]

    def best_for_symbol(self, symbol: str) -> dict[str, Any] | None:
        now = self.clock()
        mine = [s for s in self.open_signals() if s.symbol == symbol]
        if not mine:
            return None
        return self.opportunity(max(mine, key=lambda s: self._rank(s, now)))

    # --- loop / health --------------------------------------------------------------------------
    async def _loop(self) -> None:
        while True:
            try:
                mono = time.monotonic()
                for stream in list(self.streams.values()):
                    if (
                        stream.pending_close is not None
                        and mono - stream.pending_since > CONTEXT_WAIT_SECONDS
                    ):
                        self._try_evaluate(stream, force=True)
            except Exception:
                logger.exception("strategy43.tick_failed")
            await asyncio.sleep(LOOP_INTERVAL)

    async def counts(self) -> dict[str, Any]:
        if self.database is None:
            return {}
        now = int(self.clock())
        day0 = int(datetime.fromtimestamp(now, UTC).replace(hour=0, minute=0, second=0).timestamp())
        async with self.database.session_factory() as session:
            return {
                "today": await store.counts_since(session, day0),
                "7d": await store.counts_since(session, now - 7 * 86400),
                "30d": await store.counts_since(session, now - 30 * 86400),
            }

    def health(self) -> dict[str, Any]:
        now = self.clock()
        running = bool(self._tasks) and all(not t.done() for t in self._tasks[:1])
        problems: list[str] = []
        if self.problem:
            problems.append(self.problem)
        if not running:
            problems.append("محرك الإشارات متوقف (لم يبدأ أو توقف بشكل غير متوقع)")
        if self.market.health.overall == "disconnected":
            problems.append("الاتصال ببيانات السوق (OKX) مقطوع — لا يمكن تحليل شموع جديدة")
        last = self.stats["last_market_update"]
        if self.ready and last is not None and now - last > 3600 + 120:
            problems.append("لم تصل شموع مغلقة منذ أكثر من ساعة — تحقق من اتصال الإنترنت")
        if self.stats["persist_errors"]:
            problems.append(f"أخطاء حفظ: {self.stats['last_persist_error']}")
        if self.subscribe_errors:
            first = next(iter(self.subscribe_errors.items()))
            problems.append(
                f"تعذر تشغيل {len(self.subscribe_errors)} من تدفقات المحرك "
                f"(مثال {first[0][0]} {first[0][1].value}: {first[1]})"
            )
        if self.unavailable:
            problems.append("رموز غير متاحة: " + ", ".join(sorted(self.unavailable)))
        state = "stopped" if not running else "starting" if not self.ready else "running"
        if state == "running" and problems:
            state = "degraded"
        opens = self.open_signals()
        tiers: dict[str, int] = {"A+": 0, "A": 0, "B": 0, "C": 0}
        for s in opens:
            tiers[tier(s.score)] += 1
        waiting = sum(
            1 for s in self.streams.values() if s.current is not None and s.tracker.active is None
        )
        return {
            "state": state,
            "state_ar": {
                "running": "نشط",
                "starting": "قيد التشغيل",
                "degraded": "يعمل مع مشكلة",
                "stopped": "متوقف",
            }[state],
            "problems": problems,
            "name": NAME,
            "version": self.version,
            "fingerprint": self.fingerprint,
            "started_at": self.started_at,
            "universe": list(self.universe),
            "universe_size": len(self.universe),
            "streams": len(self.streams),
            "subscribed": self.subscribed,
            "markets_scanned": len({k[0] for k, s in self.streams.items() if s.evaluated_at}),
            "timeframes": list(TIMEFRAMES),
            "open_opportunities": len(opens),
            "open_by_tier": tiers,
            "symbols_with_opportunity": len({s.symbol for s in opens}),
            "wait_streams": waiting,
            "market_status": self.market.health.overall,
            **self.stats,
        }
