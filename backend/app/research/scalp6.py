"""Phase 6 research replay for wese-trade-scalp-6 (docs/research-scalp6.md).

One engine pass per (symbol, timeframe, EMA set, context pair) records every candle's
evaluations; each pre-registered configuration is then applied post hoc with the SAME pure
`choose()` the live engine uses, and traded with the Phase 5 cost-aware simulator (one
position per symbol at a time, limit entries fill only through the price).

    python -m app.research.scalp6 grid --tf 5m        # development only
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from typing import Any

from app.research.ltf5 import data, metrics, sim
from app.research.ltf5.data import DEV_END_MS, HOLDOUT_START_MS, Series
from app.research.ltf5.run import FOLDS, OUT, members
from app.research.ltf5.strategy import Candidate, Plan
from app.scalp6.engine import ContextTrend, Evaluation, Profile, Scalp6Engine, TradePlan, choose

EMA_SETS: tuple[tuple[int, int, int], ...] = ((9, 21, 50), (20, 50, 200))
CONTEXTS: dict[str, tuple[tuple[str, str], ...]] = {
    "1m": (("5m", "10m"), ("5m", "15m")),
    "5m": (("10m", "15m"), ("15m", "1h")),
    "10m": (("15m", "30m"), ("30m", "1h")),
}
FAMILY_SETS: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("A", ("A",), False),
    ("B", ("B",), False),
    ("C", ("C",), False),
    ("D", ("A", "B", "C"), True),
)
THRESHOLDS = (60.0, 70.0)
ENTRIES = ("market", "limit")
FRACTAL = {"1m": 3, "5m": 2, "10m": 2}
MIN_DEV_TRADES = 300
NO_FLOOR = sim.Config(ctx=False, floor=1.0)  # the engine's own friction blocker applies
LIMIT = sim.Config(ctx=False, floor=1.0, limit=True)


@dataclass(frozen=True, slots=True)
class Rec:
    i: int
    time: int  # signal candle close (ms)
    regime: str
    evals: tuple[Evaluation, ...]
    atr: float


def replay(
    exe: Series, ctx: tuple[Series, Series], ema: tuple[int, int, int], tf: str
) -> list[Rec]:
    prof = Profile(tf, ema=ema, fractal=FRACTAL[tf], adaptive=False, threshold=0.0)
    eng = Scalp6Engine(prof, exe.step)
    trends = [ContextTrend(), ContextTrend()]
    ptr = [0, 0]
    last_close: list[int | None] = [None, None]
    out: list[Rec] = []
    for i in range(len(exe)):
        close_ms = exe.t[i] + exe.step
        context: list[tuple[int, float]] = []
        for k, cs in enumerate(ctx):
            while ptr[k] < len(cs) and cs.t[ptr[k]] + cs.step <= close_ms:
                j = ptr[k]
                trends[k].update(cs.h[j], cs.lo[j], cs.c[j])
                last_close[k] = cs.t[j] + cs.step
                ptr[k] += 1
            lc = last_close[k]
            stale = lc is None or close_ms - lc > 2 * cs.step
            context.append((0, 0.0) if stale else trends[k].direction())
        eng.update(exe.t[i], exe.o[i], exe.h[i], exe.lo[i], exe.c[i], exe.v[i], context)
        if eng.evals:
            out.append(Rec(i, close_ms, eng.regime, tuple(eng.evals), eng.atr.value or 0.0))
    return out


def _plan(p: TradePlan) -> Plan:
    return Plan(p.entry, p.stop, p.risk, p.targets)


def to_candidate(rec: Rec, ev: Evaluation, score: float, plan: TradePlan) -> Candidate:
    hour = (rec.time // 3_600_000) % 24
    return Candidate(
        i=rec.i, time=rec.time, side=ev.side, atr=rec.atr, market=_plan(plan), limit=_plan(plan),
        ctx_dir=ev.side, disp=False, candle=False, sweep=False, vol=False, volband=False,
        ext_ok=True, too_wide=False, hour=hour, atr_pct=50.0,
        ctx_strength={"trending": 2.0, "ranging": 0.0}.get(rec.regime, 0.5),
    )  # fmt: skip


@dataclass(slots=True)
class Market:
    symbol: str
    tick: float
    exe: Series
    recs: dict[tuple[tuple[int, int, int], tuple[str, str]], list[Rec]]


def load_market(symbol: str, tick: float, tf: str, unlock: bool = False) -> Market:
    end = None if unlock else HOLDOUT_START_MS
    base5, _ = data.load(symbol, "5m", end_ms=end, unlock_holdout=unlock)
    if tf == "1m":
        exe, _ = data.load(symbol, "1m", end_ms=end, unlock_holdout=unlock)
    elif tf == "5m":
        exe = base5
    else:
        exe = data.aggregate(base5, tf)
    agg: dict[str, Series] = {"5m": base5}
    recs = {}
    for pair in CONTEXTS[tf]:
        for c in pair:
            if c not in agg:
                agg[c] = data.aggregate(base5, c)
        for ema in EMA_SETS:
            recs[(ema, pair)] = replay(exe, (agg[pair[0]], agg[pair[1]]), ema, tf)
    return Market(symbol, tick, exe, recs)


def trades(
    m: Market, ema: tuple[int, int, int], pair: tuple[str, str], prof: Profile, start: int, end: int
) -> tuple[list[sim.Trade], int]:
    """Sequential trading; returns (trades, missed limit entries)."""
    out: list[sim.Trade] = []
    missed = 0
    busy = -1
    for rec in m.recs[(ema, pair)]:
        if rec.time < start or rec.time >= end or rec.i <= busy:
            continue
        pick = choose(list(rec.evals), rec.regime, prof)
        if pick is None or pick[3]:
            continue
        ev, score, plan, _ = pick
        cfg = LIMIT if plan.entry_mode == "limit" else NO_FLOOR
        tr = sim.simulate(m.exe, to_candidate(rec, ev, score, plan), cfg, m.tick)
        if tr is None:
            missed += 1
            continue
        out.append(replace(tr, score=score))
        busy = tr.exit_index
    return out, missed


def configs(tf: str) -> list[tuple[tuple[int, int, int], tuple[str, str], Profile]]:
    out = []
    for ema, pair, (_name, fams, adaptive), thr, entry in itertools.product(
        EMA_SETS, CONTEXTS[tf], FAMILY_SETS, THRESHOLDS, ENTRIES
    ):
        prof = Profile(tf, ema, FRACTAL[tf], fams, adaptive, thr, entry)
        out.append((ema, pair, prof))
    return out


def label(ema: tuple[int, int, int], pair: tuple[str, str], prof: Profile) -> str:
    return f"ctx={'+'.join(pair)} {prof.key()}"


def neighbours(tf: str, ema: Any, pair: Any, prof: Profile) -> list[tuple[Any, Any, Profile]]:
    out = [(e, pair, replace(prof, ema=e)) for e in EMA_SETS if e != ema]
    out += [(ema, p, prof) for p in CONTEXTS[tf] if p != pair]
    out += [(ema, pair, replace(prof, threshold=t)) for t in THRESHOLDS if t != prof.threshold]
    out += [(ema, pair, replace(prof, entry=x)) for x in ENTRIES if x != prof.entry]
    return out


def select(tf: str, results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    rows = []
    for ema, pair, prof in configs(tf):
        r = results[label(ema, pair, prof)]
        if r.get("trades", 0) >= MIN_DEV_TRADES:
            rows.append((r["net_e"], ema, pair, prof))
    rows.sort(key=lambda x: -x[0])
    for e, ema, pair, prof in rows:
        if e < 0.03 or (results[label(ema, pair, prof)].get("pf") or 0) < 1.05:
            break
        neigh = [results[label(*n)] for n in neighbours(tf, ema, pair, prof)]
        if all(n.get("trades", 0) and n["net_e"] > 0 and n["net_e"] >= 0.5 * e for n in neigh):
            return {"pick": label(ema, pair, prof), "net_e": e}
    best = rows[0] if rows else None
    return {
        "pick": None,
        "reason": "no configuration meets G1 (net E >= +0.03, PF >= 1.05, n >= 300) with a plateau",
        "best": label(best[1], best[2], best[3]) if best else None,
        "best_net_e": best[0] if best else None,
    }


def _symbol_trades(
    args: tuple[str, float, str, int, int, bool],
) -> tuple[str, int, dict[str, tuple[list[sim.Trade], int]]]:
    """Worker: one symbol, every configuration, trades in [start, end)."""
    symbol, tick, tf, start, end, unlock = args
    m = load_market(symbol, tick, tf, unlock)
    out = {label(e, p, prof): trades(m, e, p, prof, start, end) for e, p, prof in configs(tf)}
    return symbol, m.exe.t[0], out


def collect(
    tf: str, start: int, end: int, unlock: bool = False
) -> tuple[dict[str, list[sim.Trade]], dict[str, int], int]:
    jobs = [(s, tick, tf, start, end, unlock) for s, tick in members()]
    per: dict[str, list[sim.Trade]] = {}
    missed: dict[str, int] = {}
    first = 2**62
    with ProcessPoolExecutor(max_workers=4) as pool:
        for _sym, t0, res in pool.map(_symbol_trades, jobs):
            first = min(first, t0)
            for k, (tr, ms) in res.items():
                per.setdefault(k, []).extend(tr)
                missed[k] = missed.get(k, 0) + ms
    return per, missed, first


def cmd_grid(tf: str) -> dict[str, Any]:
    t0 = time.time()
    per, missed, first = collect(tf, 0, DEV_END_MS)
    days = (DEV_END_MS - first) / metrics.DAY_MS
    results: dict[str, dict[str, Any]] = {}
    for k, tr in per.items():
        r = metrics.summary(tr, days)
        r["missed_entries"] = missed[k]
        r["long_e"] = metrics.summary([t for t in tr if t.side == 1]).get("net_e")
        r["short_e"] = metrics.summary([t for t in tr if t.side == -1]).get("net_e")
        results[k] = r
    pick = select(tf, results)
    out = {"tf": tf, "segment": "dev", "days": round(days, 1), "results": results,
           "selection": pick, "seconds": round(time.time() - t0, 1)}  # fmt: skip
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"scalp6_{tf}_dev_grid.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"== scalp6 {tf} dev ({days:.0f} days, {out['seconds']}s)")
    for k, r in sorted(results.items(), key=lambda kv: -kv[1].get("net_e", -9))[:20]:
        print(
            f"  {k:66} n={r.get('trades', 0):6} win={r.get('win_rate', 0):.2f} "
            f"gross={r.get('gross_e', 0):+.3f} net={r.get('net_e', 0):+.3f} pf={r.get('pf')} "
            f"dd={r.get('max_dd')} /day={r.get('per_day')} L={r.get('long_e')} S={r.get('short_e')}"
        )
    for fam in ("A", "B", "C", "D"):
        rows = [r | {"k": k} for k, r in results.items() if f"fam={fam} " in k and r.get("trades")]
        if rows:
            best = max(rows, key=lambda r: r.get("net_e", -9))
            print(f"  best {fam}: {best['k']} n={best.get('trades')} gross={best.get('gross_e')} "
                  f"net={best.get('net_e')} pf={best.get('pf')}")  # fmt: skip
    print("  selection:", json.dumps(pick))
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["grid"])
    p.add_argument("--tf", choices=list(CONTEXTS), default="5m")
    a = p.parse_args()
    cmd_grid(a.tf)


if __name__ == "__main__":
    main()

__all__ = ["FOLDS", "load_market", "trades"]
