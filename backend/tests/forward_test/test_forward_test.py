"""Phase 4.2 forward test: frozen version, boundary, no retroactive signals, restart,
persistence, lifecycle, pause/resume/stop, checkpoints, metrics, pass/fail, API, export."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import asdict, replace
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import delete, func, select

from app.analysis.engine import MarketAnalyzer
from app.core.config import Settings
from app.core.state import AppResources
from app.db.base import Base
from app.db.session import Database
from app.forward_test import store
from app.forward_test.candidate import (
    CRITERIA,
    RESEARCH_VERSION,
    candidate,
    fingerprint,
    forward_version,
    frozen_config,
)
from app.forward_test.codec import freeze, lifecycle, thaw
from app.forward_test.evaluate import LiveContext, evaluate_candle
from app.forward_test.metrics import assess, closed_trades, score_bucket, summary
from app.market_data.timeframes import Timeframe
from app.models.forward_test import (
    ForwardTestCheckpoint,
    ForwardTestCursor,
    ForwardTestRun,
    ForwardTestSignal,
)
from app.research.collect import collect
from app.research.simulate import evaluation
from app.signal_engine.enums import ExitReason, SignalState
from app.signal_engine.models import Signal
from tests.analysis.helpers import load_fixture
from tests.conftest import ADMIN_PASSWORD, ADMIN_USERNAME
from tests.forward_test.helpers import (
    KEY,
    FakeAnalysis,
    FakeMarket,
    candles,
    drive,
    make_service,
    open_time,
    stub_evaluator,
)
from tests.signals.test_backtest import LENIENT, _aggregate

FROZEN_VERSION = "wese-trade-forward-4.2-a03e20f1d4"


# --- frozen strategy -----------------------------------------------------------------------
def test_frozen_candidate_and_version_are_immutable() -> None:
    v = candidate()
    assert v.version == RESEARCH_VERSION == "wese-trade-research-4.1-c590e82e3a"
    d = v.definition()
    assert d["families"] == ("TREND_CONTINUATION",) and d["threshold"] == 75.0
    assert d["entry"] == "retrace" and d["runner"] is True and d["break_even"] is False
    assert d["excluded_regimes"] == ("range", "transitional") and d["costs"] == "base"
    config = frozen_config()
    assert forward_version(config) == FROZEN_VERSION
    assert fingerprint(FROZEN_VERSION) == "4.2-a03e20f"
    assert config["timeframes"] == ["15m", "30m", "1h"]
    assert config["cost_model"] == {
        "name": "base",
        "fee_rate": 0.0005,
        "maker_fee_rate": 0.0002,
        "slippage_rate": 0.0002,
    }
    # any change to anything that defines a signal produces a NEW version
    for key, value in (("timeframes", ["15m"]), ("universe", ["BTCUSDT"]), ("protocol", "x")):
        assert forward_version({**config, key: value}) != FROZEN_VERSION
    changed = {**config, "variant": {**config["variant"], "threshold": 74.0}}
    assert forward_version(changed) != FROZEN_VERSION


def test_live_evaluation_equals_research_evaluation() -> None:
    """The live path is the research path: identical evaluations on every trigger candle."""
    raw, tick = load_fixture("okx_btcusdt_5m")
    tf = Timeframe.M15
    bars15 = _aggregate(raw, tf)
    ctx = {
        Timeframe.M30: _aggregate(raw, Timeframe.M30),
        Timeframe.H1: _aggregate(raw, Timeframe.H1),
    }
    v = replace(candidate(), threshold=40.0, spread=0.0)  # lenient: the fixture is short
    research = collect("BTCUSDT", tf, bars15, ctx, tick=tick, config=LENIENT)
    expected = {t.index: evaluation(v, research, t) for t in research.triggers}
    analyzer = MarketAnalyzer("BTCUSDT", tf, tick_size=tick)
    ctx_an = {c: MarketAnalyzer("BTCUSDT", c, tick_size=tick) for c in ctx}
    pos = dict.fromkeys(ctx, 0)
    compared = 0
    for c in bars15:
        close_ms = c.open_ms + tf.milliseconds
        for ctf, series in ctx.items():
            while (
                pos[ctf] < len(series) and series[pos[ctf]].open_ms + ctf.milliseconds <= close_ms
            ):
                ctx_an[ctf].update(series[pos[ctf]])
                pos[ctf] += 1
        analyzer.update(c)
        idx = analyzer.series.last.index
        if idx not in expected:
            continue
        live = evaluate_candle(
            v,
            analyzer,
            [ctx_an[c2].frame() for c2 in ctx],
            LiveContext(False, True),
            strategy_version="x",
            config=LENIENT,
        )
        exp = expected[idx]
        assert (live.signal_class.value, live.plan) == (
            (exp.signal_class.value, exp.plan) if exp else ("NEUTRAL", None)
        )
        compared += 1
    assert compared > 10


# --- service harness ---------------------------------------------------------------------------
@pytest.fixture
async def database(settings: Settings) -> AsyncIterator[Database]:
    db = Database(settings)
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield db
    await db.dispose()


async def _create_run(database: Database, start_index: int, version: str = FROZEN_VERSION) -> int:
    async with database.session_factory() as session:
        run = await store.create_run(
            session,
            version=version,
            fingerprint=fingerprint(version),
            research_version=RESEARCH_VERSION,
            config=frozen_config(),
            started_at=datetime.fromtimestamp(open_time(start_index), tz=UTC),
            symbols=["BTCUSDT"],
            timeframes=["15m"],
            cost_model={"name": "base"},
            minimum_required_trades=150,
            minimum_days=30,
        )
        return run.id


async def _boot(
    database: Database,
    data: list[Any],
    seed: int,
    monkeypatch: pytest.MonkeyPatch,
    buy_at: set[int],
    **kw: Any,
) -> tuple[Any, MarketAnalyzer, list[float]]:
    monkeypatch.setattr("app.forward_test.service.evaluate_candle", stub_evaluator(buy_at, **kw))
    analysis, market, clock = FakeAnalysis(), FakeMarket(), [0.0]
    service = make_service(database, analysis, market, clock)
    await service.start(background_loop=False)
    assert await service.load()
    analyzer = MarketAnalyzer("BTCUSDT", Timeframe.M15, tick_size=0.1)
    for c in data[:seed]:
        analyzer.update(c)
    analysis.analyzers[KEY] = analyzer
    clock[0] = analyzer.series.last.close_time + 5
    service.on_seeded(KEY, analyzer)
    return service, analyzer, clock


async def _rows(database: Database) -> list[ForwardTestSignal]:
    async with database.session_factory() as session:
        return list((await session.execute(select(ForwardTestSignal))).scalars())


async def test_start_boundary_and_no_retroactive_signals(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = candles(320)
    await _create_run(database, start_index=250)
    # 260 and 275 are AFTER the start but only seen in the seeded history: never signals.
    service, analyzer, clock = await _boot(
        database, data, 280, monkeypatch, {200, 260, 275, 285, 300}
    )
    drive(service, analyzer, data[280:290], clock)
    await service.flush()
    rows = await _rows(database)
    assert len(rows) == 1 and rows[0].frozen["trigger_id"] == "t285"
    assert rows[0].confirmed_at == datetime.fromtimestamp(
        analyzer.series.bar(285).close_time, tz=UTC
    )
    assert service.stats["evaluations"] == 10  # every live candle after the boundary
    await service.stop()


async def test_live_candles_before_start_are_not_evaluated(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = candles(320)
    await _create_run(database, start_index=290)
    service, analyzer, clock = await _boot(database, data, 280, monkeypatch, {285, 295})
    drive(service, analyzer, data[280:300], clock)
    await service.flush()
    rows = await _rows(database)
    assert len(rows) == 1 and rows[0].frozen["trigger_id"] == "t295"
    assert service.stats["evaluations"] == 10  # 290..299 only
    await service.stop()


async def test_stale_feed_or_inactive_symbol_never_signals(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = candles(320)
    await _create_run(database, start_index=250)
    service, analyzer, clock = await _boot(database, data, 280, monkeypatch, {282, 284, 286})
    service.market.state = "stale"
    drive(service, analyzer, data[280:283], clock)
    service.market.state = "live"
    service.market.inactive.add("BTCUSDT")
    drive(service, analyzer, data[283:285], clock)
    service.market.inactive.clear()
    # a candle processed too long after its close is not "current" -> stale
    analyzer.update(data[285])
    clock[0] = analyzer.series.last.close_time + 3600
    service.on_closed(KEY, analyzer)
    await service.flush()
    assert await _rows(database) == []
    await service.stop()


async def test_restart_resumes_cursor_restores_open_signal_without_duplicates(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = candles(340)
    await _create_run(database, start_index=250)
    # uninterrupted reference run
    ref_db_service, ref_an, ref_clock = await _boot(database, data, 280, monkeypatch, {285})
    drive(ref_db_service, ref_an, data[280:330], ref_clock)
    reference = ref_db_service.streams[KEY].tracker
    ref_signal = next(iter([*reference.closed, *([reference.active] if reference.active else [])]))
    await ref_db_service.stop()
    # second database: same run, interrupted at 288, down 289..299, back at 300
    async with database.session_factory() as session:
        await session.execute(delete(ForwardTestSignal))
        await session.execute(delete(ForwardTestCursor))
        await session.commit()
    a, an_a, clock_a = await _boot(database, data, 280, monkeypatch, {285})
    drive(a, an_a, data[280:289], clock_a)
    await a.stop()
    cursor_before = (await _cursors(database))[("BTCUSDT", "15m")]
    assert cursor_before == an_a.series.last.close_time
    # restart: seed history now includes 289..299 (closed while down); 292 "would" signal
    b, an_b, clock_b = await _boot(database, data, 300, monkeypatch, {285, 292})
    assert b.streams[KEY].catchup_candles == 11
    drive(b, an_b, data[300:330], clock_b)
    await b.flush()
    rows = await _rows(database)
    assert len(rows) == 1 and rows[0].frozen["trigger_id"] == "t285"  # no duplicate, no t292
    restored = thaw(rows[0].frozen, rows[0].lifecycle)
    assert (restored.state, restored.net_r, restored.targets_hit) == (
        ref_signal.state,
        ref_signal.net_r,
        ref_signal.targets_hit,
    )
    assert (await _cursors(database))[("BTCUSDT", "15m")] == an_b.series.last.close_time
    await b.stop()


async def _cursors(database: Database) -> dict[tuple[str, str], int]:
    async with database.session_factory() as session:
        run = await store.open_run(session)
        assert run is not None
        return await store.cursors(session, run.id)


async def test_retrace_paper_fill_only_when_touched_and_expiry(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = candles(320)
    await _create_run(database, start_index=250)
    # limit 50 below the close: never touched -> expires after 6 bars, never a trade
    service, analyzer, clock = await _boot(
        database, data, 280, monkeypatch, {282}, zone_offset=50.0
    )
    drive(service, analyzer, data[280:300], clock)
    await service.flush()
    signals = await _signals(database)
    assert len(signals) == 1 and signals[0].state is SignalState.EXPIRED and not signals[0].entered
    s = summary(signals, CRITERIA)
    assert s["counts"]["expired_unfilled"] == 1 and s["counts"]["closed_trades"] == 0
    await service.stop()


async def _signals(database: Database) -> list[Signal]:
    async with database.session_factory() as session:
        run = (
            (await session.execute(select(ForwardTestRun).order_by(ForwardTestRun.id.desc())))
            .scalars()
            .first()
        )
        assert run is not None
        return await store.load_signals(session, run.id)


async def test_pause_resume_stop(database: Database, monkeypatch: pytest.MonkeyPatch) -> None:
    data = candles(340)
    run_id = await _create_run(database, start_index=250)
    service, analyzer, clock = await _boot(database, data, 280, monkeypatch, {282, 290, 300})
    drive(service, analyzer, data[280:285], clock)  # 282 -> signal (market entry)
    await service.set_status("paused", "maintenance")
    held = service.streams[KEY].tracker.active
    drive(service, analyzer, data[285:295], clock)  # 290 ignored while paused
    assert held is None or held.bars_held > 0 or held.state.is_final  # lifecycle continued
    await service.set_status("forward_testing", "resume")
    drive(service, analyzer, data[295:302], clock)  # 300 evaluated again
    await service.set_status("stopped", "end")
    await service.flush()
    rows = await _rows(database)
    assert sorted(r.frozen["trigger_id"] for r in rows) == ["t282", "t300"]
    for s in await _signals(database):
        assert s.state.is_final  # open ones ended as END_OF_DATA by the stop
    async with database.session_factory() as session:
        run = await session.get(ForwardTestRun, run_id)
        assert run is not None and run.status == "stopped" and run.stopped_at is not None
        assert [h[1] for h in run.status_history] == [
            "forward_testing",
            "paused",
            "forward_testing",
            "stopped",
        ]
        with pytest.raises(store.InvalidRunTransitionError):
            await store.set_status(session, run_id, "forward_testing", "x", datetime.now(UTC))
    # a stopped run frees the version: a new run may start (never two open ones)
    await _create_run(database, start_index=330)
    with pytest.raises(store.RunConflictError):
        await _create_run(database, start_index=331)
    await service.stop()


async def test_changed_strategy_refuses_existing_run(database: Database) -> None:
    await _create_run(database, start_index=250, version="wese-trade-forward-4.2-0000000000")
    service = make_service(database, FakeAnalysis(), FakeMarket(), [0.0])
    assert not await service.load()
    assert service.problem and "frozen strategy changed" in service.problem
    assert service.health()["state"] == "degraded"


async def test_checkpoint_is_stored_once_per_day(
    database: Database, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = candles(320)
    await _create_run(database, start_index=250)
    service, _an, _clock = await _boot(database, data, 280, monkeypatch, set())
    metrics = await service.checkpoint()
    assert metrics is not None and metrics["assessment"]["verdict"] == "INSUFFICIENT_SAMPLE"
    await service.checkpoint()
    async with database.session_factory() as session:
        count = (
            await session.execute(select(func.count()).select_from(ForwardTestCheckpoint))
        ).scalar_one()
    assert count == 1
    await service.stop()


# --- codec / metrics / criteria -------------------------------------------------------------
def _closed(
    i: int,
    net: float,
    *,
    symbol: str = "BTCUSDT",
    tf: str = "15m",
    score: float = 78.0,
    state: SignalState = SignalState.TP3_HIT,
) -> Signal:
    base = _template()
    return replace(
        base,
        id=f"s{i}",
        symbol=symbol,
        timeframe=tf,
        score=score,
        confirmed_time=1_790_000_000 + i * 900,
        closed_time=1_790_000_000 + i * 900 + 3600,
        entered_time=1_790_000_000 + i * 900,
        entry_price=100.0,
        state=state,
        exit_reason=ExitReason.TP3 if net > 0 else ExitReason.STOP,
        net_r=net,
        gross_r=net + 0.1,
        bars_held=4,
        exits=[(1.0, 102.0, "tp3")],
    )


_TEMPLATE: list[Signal] = []


def _template() -> Signal:
    if not _TEMPLATE:
        from app.signal_engine.lifecycle import SignalTracker
        from tests.forward_test.helpers import stub_evaluator as se

        an = MarketAnalyzer("BTCUSDT", Timeframe.M15, tick_size=0.1)
        for c in candles(5):
            an.update(c)
        ev = se({4})(candidate(), an, [], LiveContext(False, True), strategy_version=FROZEN_VERSION)
        tracker = SignalTracker("BTCUSDT", "15m", candidate().tracker_config(), step_seconds=900)
        sig = tracker.on_evaluation(ev, an.series.last)
        assert sig is not None
        _TEMPLATE.append(sig)
    return _TEMPLATE[0]


def test_codec_round_trip_is_exact() -> None:
    s = _closed(1, 1.5)
    assert thaw(freeze(s), lifecycle(s)) == s


def test_metrics_counts_and_buckets() -> None:
    sigs = [_closed(i, 1.0 if i % 3 else -1.0, score=76 + i) for i in range(12)]
    expired = replace(_template(), id="e", state=SignalState.EXPIRED, entered_time=None)
    eod = replace(_closed(99, 0.5), exit_reason=ExitReason.END_OF_DATA, state=SignalState.CLOSED)
    s = summary([*sigs, expired, eod], CRITERIA)
    assert s["counts"]["closed_trades"] == 12 and s["counts"]["expired_unfilled"] == 1
    assert s["counts"]["ended_by_run_stop"] == 1
    assert s["all"]["expectancy"] == pytest.approx((8 - 4) / 12, abs=1e-3)
    assert s["all"]["profit_factor"] == pytest.approx(2.0)
    assert set(s["by_score_bucket"]) <= {"75-79", "80-84", "85-89", "90+"}
    assert score_bucket(91) == "90+" and score_bucket(79.99) == "75-79"
    assert len(closed_trades(sigs)) == 12 and s["recent"]["entered"] == 12


def test_assessment_requires_sample_duration_and_every_criterion() -> None:
    good = [
        _closed(
            i,
            1.0 if i % 2 else -0.5,
            symbol=("BTCUSDT", "ETHUSDT", "SOLUSDT")[i % 3],
            tf=("15m", "30m", "1h")[i % 3 - 1],
        )
        for i in range(160)
    ]
    assert assess(good[:100], 40, CRITERIA).verdict == "INSUFFICIENT_SAMPLE"  # too few trades
    assert assess(good, 10, CRITERIA).verdict == "INSUFFICIENT_SAMPLE"  # too little time
    assert assess(good, 40, CRITERIA).verdict == "PASS_CRITERIA_MET"
    one_symbol = [replace(s, symbol="BTCUSDT") for s in good]
    assert assess(one_symbol, 40, CRITERIA).verdict == "CONTINUE"
    collapse = good[:-30] + [replace(s, net_r=-1.0) for s in good[-30:]]
    v = assess(collapse, 40, CRITERIA)
    assert v.verdict == "CONTINUE" and any("recent" in r for r in v.reasons)


def test_failure_needs_sufficient_negative_evidence() -> None:
    bad = [_closed(i, -1.0 if i % 4 else 1.0) for i in range(40)]
    assert assess(bad, 60, CRITERIA).verdict == "INSUFFICIENT_SAMPLE"  # a short streak never fails
    bad = [
        _closed(i, -1.0 if i % 4 else 1.0, symbol=f"S{i % 6}USDT", tf=("15m", "30m", "1h")[i % 3])
        for i in range(80)
    ]
    v = assess(bad, 60, CRITERIA)
    assert v.verdict == "FAIL_CRITERIA_MET" and len(v.reasons) >= 2


# --- API -------------------------------------------------------------------------------------
@pytest.fixture
async def api(
    app: FastAPI, admin_user: Any
) -> AsyncIterator[tuple[httpx.AsyncClient, AppResources]]:
    resources: AppResources = app.state.resources
    service = make_service(resources.database, FakeAnalysis(), FakeMarket(), [1_790_300_000.0])
    resources.forward_test = service
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        login = {"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}
        assert (await client.post("/api/v1/auth/login", json=login)).status_code == 200
        yield client, resources


async def test_api_status_runs_signals_export_and_controls(
    api: tuple[httpx.AsyncClient, AppResources], monkeypatch: pytest.MonkeyPatch
) -> None:
    client, resources = api
    body = (await client.get("/api/v1/forward-test/status")).json()
    assert body["run"] is None and body["fingerprint"] == "4.2-a03e20f"
    assert body["disclaimer_ar"] == "الإشارات قيد الاختبار وليست توصيات مضمونة."
    database = resources.database
    run_id = await _create_run(database, start_index=250)
    service = resources.forward_test
    assert service is not None
    data = candles(320)
    monkeypatch.setattr("app.forward_test.service.evaluate_candle", stub_evaluator({285}))
    await service.start(background_loop=False)
    assert await service.load()
    an = MarketAnalyzer("BTCUSDT", Timeframe.M15, tick_size=0.1)
    for c in data[:280]:
        an.update(c)
    service.analysis.analyzers[KEY] = an  # type: ignore[attr-defined]
    clock = [an.series.last.close_time + 5.0]
    service.clock = lambda: clock[0]
    service.on_seeded(KEY, an)
    drive(service, an, data[280:320], clock)
    await service.flush()
    status_body = (await client.get("/api/v1/forward-test/status")).json()
    assert (
        status_body["run"]["status_ar"] == "اختبار مباشر" and status_body["confirmed_signals"] == 1
    )
    detail = (await client.get(f"/api/v1/forward-test/runs/{run_id}")).json()
    assert detail["config_matches_code"] is True and detail["metrics"]["counts"]["confirmed"] == 1
    assert detail["metrics"]["assessment"]["verdict"] == "INSUFFICIENT_SAMPLE"
    items = (
        await client.get(f"/api/v1/forward-test/runs/{run_id}/signals", params={"side": "long"})
    ).json()["items"]
    assert (
        len(items) == 1 and items[0]["symbol"] == "BTCUSDT" and items[0]["tp3"] > items[0]["entry"]
    )
    assert (
        await client.get(f"/api/v1/forward-test/runs/{run_id}/signals", params={"side": "short"})
    ).json()["items"] == []
    # chart markers: exactly the persisted signal, never recomputed; research TFs empty
    chart = (
        await client.get(
            "/api/v1/forward-test/chart-signals", params={"symbol": "btcusdt", "timeframe": "15m"}
        )
    ).json()
    assert chart["signal_capable"] is True and chart["fingerprint"] == "4.2-a03e20f"
    assert [m["id"] for m in chart["items"]] == [r.signal_id for r in await _rows(database)]
    marker = chart["items"][0]
    assert marker["side"] == "long" and marker["strategy_version"] == FROZEN_VERSION
    assert marker["trigger_time"] == open_time(285)  # the confirmation candle (open time)
    assert marker["confirmed_time"] == open_time(286)  # its close
    assert marker["plan"]["targets"][2]["price"] == items[0]["tp3"]
    later = {"symbol": "BTCUSDT", "timeframe": "15m", "since": marker["confirmed_time"] + 1}
    assert (await client.get("/api/v1/forward-test/chart-signals", params=later)).json()[
        "items"
    ] == []
    for params in (
        {"symbol": "BTCUSDT", "timeframe": "5m"},
        {"symbol": "ETHUSDT", "timeframe": "15m"},
    ):
        body = (await client.get("/api/v1/forward-test/chart-signals", params=params)).json()
        assert body["items"] == []
        assert body["signal_capable"] is (params["timeframe"] == "15m")
    exported = await client.get(
        f"/api/v1/forward-test/runs/{run_id}/export", params={"format": "json"}
    )
    blob = exported.text
    assert exported.status_code == 200 and '"signals"' in blob and FROZEN_VERSION in blob
    assert "secret" not in blob.lower() and "password" not in blob.lower()
    csv = await client.get(f"/api/v1/forward-test/runs/{run_id}/export", params={"format": "csv"})
    assert csv.text.splitlines()[1].startswith("signal_id,strategy_version,symbol")
    assert len(csv.text.strip().splitlines()) == 3
    paused = await client.post(f"/api/v1/forward-test/runs/{run_id}/pause", json={"note": "x"})
    assert paused.status_code == 200 and paused.json()["status"] == "paused"
    assert (await client.post(f"/api/v1/forward-test/runs/{run_id}/resume", json={})).json()[
        "status"
    ] == "forward_testing"
    await service.stop()


def test_no_tuning_endpoints(app: FastAPI) -> None:
    """The frozen strategy has no write endpoint except pause/resume/stop."""
    paths = app.openapi()["paths"]
    writes = sorted(
        (path, method)
        for path, ops in paths.items()
        if "/forward-test" in path
        for method in ops
        if method != "get"
    )
    assert [m for _, m in writes] == ["post", "post", "post"]
    assert [p.rsplit("/", 1)[-1] for p, _ in writes] == ["pause", "resume", "stop"]


def test_criteria_documented_values() -> None:
    assert asdict(CRITERIA)["min_closed_trades"] == 150 and CRITERIA.min_days == 30
    assert CRITERIA.min_profit_factor > 1.0 and CRITERIA.fail_min_trades >= 50
