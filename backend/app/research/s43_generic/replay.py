"""Strategy 4.3 research: replay, lifecycle simulation with costs, and config comparison.

Replay (expensive, once per series): the canonical MarketAnalyzer + context frames feed
`Strategy43` with a *loose* config (no tier / margin cut), so every candle with a setup
and a valid plan is recorded with both side scores. Tier thresholds and the margin are
then applied in the cheap simulation step, so many configs are compared on identical
evidence without replaying the market again.

Simulation (no look-ahead): the signal is known at the candle close; entry is a market
order at the NEXT candle's open (skipped when that open is already past the stop or TP1),
stop first when stop and target fall in one candle, 1/3 exits at TP1 / TP2 / TP3, stop to
break-even after TP1, expiry after a fixed holding limit. Costs: taker fee + slippage on
entry and exit (the Phase-4 "base" scenario). One open trade per stream.
"""

from __future__ import annotations

import pickle
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

from app.analysis.config import DEFAULT_CONFIG as ANALYSIS_CONFIG
from app.analysis.engine import MarketAnalyzer
from app.analysis.multi_timeframe.context import context_timeframes
from app.market_data.timeframes import Timeframe
from app.research.s43_generic.engine import DEFAULT_CONFIG, Config, Strategy43
from app.research.store import RESEARCH_DIR, ResearchStore

S43_DIR = RESEARCH_DIR / "s43"
FIXED_TIME = datetime(2020, 1, 1, tzinfo=UTC)
LOOSE = replace(DEFAULT_CONFIG, tier_c=0.0, tier_b=0.0, tier_a=0.0, tier_a_plus=0.0, margin=-100.0)
MAX_HOLD = {"15m": 96, "30m": 64, "1h": 48}
COST_FRAC = 2 * (0.0005 + 0.0002)  # base scenario: taker + slippage, entry and exit


@dataclass(frozen=True, slots=True)
class Candidate:
    index: int
    time: int  # candle open time (s)
    side: int
    score: float
    other: float
    family: str
    strength: float
    entry: float
    stop: float
    targets: tuple[float, float, float]
    regime: str
    trend: str


@dataclass(slots=True)
class Replay:
    symbol: str
    timeframe: str
    times: list[int]
    opens: list[float]
    highs: list[float]
    lows: list[float]
    closes: list[float]
    evaluated: int  # candles after warm-up
    candidates: list[Candidate]


def replay(symbol: str, tf: str, start_ms: int | None = None, tick: float = 1e-8) -> Replay:
    timeframe = Timeframe(tf)
    store = ResearchStore()
    try:
        candles = store.load(symbol, timeframe, start_ms=start_ms)
        ctx_tfs = context_timeframes(timeframe)
        context = {c: store.load(symbol, c, start_ms=start_ms) for c in ctx_tfs}
    finally:
        store.close()
    analyzer = MarketAnalyzer(symbol, timeframe, tick_size=tick, config=ANALYSIS_CONFIG)
    ctx_an = {c: MarketAnalyzer(symbol, c, tick_size=tick, config=ANALYSIS_CONFIG) for c in ctx_tfs}
    ctx_pos = dict.fromkeys(ctx_tfs, 0)
    strat = Strategy43(symbol, tf, timeframe.seconds, LOOSE)
    out = Replay(symbol, tf, [], [], [], [], [], 0, [])
    for candle in candles:
        close_ms = candle.open_ms + timeframe.milliseconds
        for c in ctx_tfs:
            series = context[c]
            i = ctx_pos[c]
            while i < len(series) and series[i].open_ms + c.milliseconds <= close_ms:
                ctx_an[c].update(series[i])
                i += 1
            ctx_pos[c] = i
        analyzer.update(candle)
        bar = analyzer.series.last
        frames = [ctx_an[c].frame() for c in ctx_tfs]
        snap = analyzer.snapshot(None, context=frames, generated_at=FIXED_TIME)
        ev = strat.update(bar, snap)
        out.times.append(bar.time)
        out.opens.append(bar.open)
        out.highs.append(bar.high)
        out.lows.append(bar.low)
        out.closes.append(bar.close)
        if not ev.blockers or ev.blockers[0] != "بيانات غير كافية بعد":
            out.evaluated += 1
        if ev.actionable and ev.plan is not None and ev.setup is not None:
            other = ev.sell_score if ev.side == 1 else ev.buy_score
            out.candidates.append(
                Candidate(
                    len(out.times) - 1,
                    bar.time,
                    ev.side,
                    ev.score,
                    other,
                    ev.setup.family.value,
                    ev.setup.strength,
                    ev.plan.entry,
                    ev.plan.stop,
                    ev.plan.targets,
                    ev.regime,
                    ev.trend,
                )
            )
    return out


def path_for(symbol: str, tf: str) -> Path:
    return S43_DIR / f"{symbol}_{tf}.pkl"


def _job(args: tuple[str, str, int | None]) -> str:
    symbol, tf, start = args
    r = replay(symbol, tf, start)
    p = path_for(symbol, tf)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as fh:
        pickle.dump(r, fh, protocol=pickle.HIGHEST_PROTOCOL)
    return f"{symbol} {tf}: {len(r.times)} bars, {len(r.candidates)} candidates"


def run_replays(jobs: Sequence[tuple[str, str, int | None]], workers: int = 4) -> list[str]:
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_job, jobs))


def load(symbol: str, tf: str) -> Replay:
    with path_for(symbol, tf).open("rb") as fh:
        r: Replay = pickle.load(fh)  # noqa: S301 - our own local research cache
        return r


@dataclass(frozen=True, slots=True)
class Trade:
    symbol: str
    timeframe: str
    time: int
    side: int
    tier: str
    score: float
    family: str
    net_r: float
    exit: str  # stop | tp3 | expiry | be
    hit: int  # number of targets reached


@dataclass(frozen=True, slots=True)
class ExitModel:
    """Entry / exit mechanics (same cost conventions as the Strategy 4.2 lifecycle)."""

    entry: str = "retrace"  # retrace (limit at the confirmation-candle midpoint) | market
    entry_bars: int = 6  # limit validity (WAITING FOR ENTRY -> EXPIRED)
    fractions: tuple[float, float, float] = (0.5, 0.0, 0.5)  # runner: 1/2 TP1, 1/2 TP3
    break_even: bool = False


TAKER, MAKER, SLIP = 0.0005, 0.0002, 0.0002


def simulate(
    r: Replay,
    cfg: Config,
    start: int = 0,
    end: int = 2**62,
    model: ExitModel = ExitModel(),
) -> list[Trade]:
    """Trades for one replayed series under the config's tier and margin rules."""
    trades: list[Trade] = []
    busy_until = -1
    n = len(r.times)
    hold = MAX_HOLD.get(r.timeframe, 64)
    fr = model.fractions
    for c in r.candidates:
        if not start <= c.time < end or c.index <= busy_until or c.index + 1 >= n:
            continue
        if c.score - c.other < cfg.margin:
            continue
        tier = cfg.tier(c.score)
        if tier == "WAIT":
            continue
        d = c.side
        # --- entry ---------------------------------------------------------------------
        if model.entry == "market":
            entry, j0, entry_cost = r.opens[c.index + 1], c.index + 1, TAKER + SLIP
            if d * (entry - c.stop) <= 0 or d * (c.targets[0] - entry) <= 0:
                continue
        else:
            mid = (r.highs[c.index] + r.lows[c.index]) / 2
            base_risk = d * (c.entry - c.stop)
            floor = max(0.5 * base_risk, 3 * 2 * (TAKER + SLIP) * c.entry)
            limit = min(mid, c.entry) if d == 1 else max(mid, c.entry)
            limit = max(limit, c.stop + floor) if d == 1 else min(limit, c.stop - floor)
            limit = min(limit, c.entry) if d == 1 else max(limit, c.entry)
            entry, j0, entry_cost = limit, -1, MAKER
            for k in range(c.index + 1, min(n, c.index + 1 + model.entry_bars)):
                if (r.lows[k] <= c.stop) if d == 1 else (r.highs[k] >= c.stop):
                    break  # invalidated before the fill
                if (r.highs[k] >= c.targets[0]) if d == 1 else (r.lows[k] <= c.targets[0]):
                    break  # ran to TP1 without us: entry missed
                if (r.lows[k] <= limit) if d == 1 else (r.highs[k] >= limit):
                    j0 = k
                    break
            if j0 < 0:
                busy_until = c.index + model.entry_bars
                continue
        risk = d * (entry - c.stop)
        if risk <= 0:
            continue
        stop = c.stop
        hit = 0
        open_frac = 1.0
        pnl = -entry_cost * entry  # price units per unit size
        exit_kind = "expiry"
        last = min(n - 1, j0 + hold)
        j = j0
        while j <= last:
            hi, lo = r.highs[j], r.lows[j]
            if (lo <= stop) if d == 1 else (hi >= stop):
                px = stop - d * SLIP * stop
                pnl += open_frac * (d * (px - entry) - TAKER * px)
                open_frac = 0.0
                exit_kind = "be" if hit else "stop"
                break
            while hit < 3 and ((hi >= c.targets[hit]) if d == 1 else (lo <= c.targets[hit])):
                part = fr[hit] if hit < 2 else open_frac
                if part > 0:
                    t = c.targets[hit]
                    pnl += part * (d * (t - entry) - MAKER * t)
                    open_frac -= part
                hit += 1
                if model.break_even:
                    stop = entry
            if hit == 3 or open_frac <= 1e-9:
                exit_kind = "tp3" if hit == 3 else f"tp{hit}"
                break
            j += 1
        else:
            j = last
        if open_frac > 1e-9:
            px = r.closes[j] - d * SLIP * r.closes[j]
            pnl += open_frac * (d * (px - entry) - TAKER * px)
        trades.append(
            Trade(
                r.symbol,
                r.timeframe,
                c.time,
                d,
                tier,
                c.score,
                c.family,
                round(pnl / risk, 4),
                exit_kind,
                hit,
            )
        )
        busy_until = j
    return trades


@dataclass(frozen=True, slots=True)
class Metrics:
    n: int
    per_day: float
    win: float
    expectancy: float
    pf: float
    avg_r: float
    max_dd: float
    long_share: float


def metrics(trades: Iterable[Trade], days: float) -> Metrics:
    ts = sorted(trades, key=lambda t: t.time)
    if not ts:
        return Metrics(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    rs = [t.net_r for t in ts]
    wins = [x for x in rs if x > 0]
    losses = [-x for x in rs if x < 0]
    eq = peak = dd = 0.0
    for x in rs:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    pf = sum(wins) / sum(losses) if losses else float("inf")
    return Metrics(
        len(ts),
        len(ts) / days,
        len(wins) / len(ts),
        sum(rs) / len(ts),
        pf,
        sum(rs) / len(ts),
        dd,
        sum(1 for t in ts if t.side == 1) / len(ts),
    )
