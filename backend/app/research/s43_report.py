"""Before / after report: frozen Strategy 4.2 vs Strategy 4.3 (docs/strategy-4.3.md).

    python -m app.research.s43_report [out.json]

Uses the pass-1 research cache (data/research/pass1) and the canonical lifecycle
simulator; windows are fixed (development / validation / holdout / common year).
"""

from __future__ import annotations

import collections
import json
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from app.forward_test.candidate import candidate
from app.research.pass1 import load_series
from app.research.simulate import run
from app.research.universe import load as load_universe
from app.strategy43.config import tier, variant

C0, DEV, VAL, END = 1759536000, 1775001600, 1782864000, 1791158400
WINDOWS = {"dev": (C0, DEV), "validation": (DEV, VAL), "holdout": (VAL, END), "year": (C0, END)}
TIMEFRAMES = ("15m", "30m", "1h")
Row = tuple[str, str, str, int, str, float, str, float | None, int]


def _job(args: tuple[str, str, str]) -> list[Row]:
    name, symbol, tf = args
    v = candidate() if name == "4.2" else variant()
    return [
        (
            name, symbol, tf, s.confirmed_time, s.side.value, s.score, s.family.value,
            s.net_r if s.entered else None, s.closed_time or s.state_time,
        )
        for s in run(v, load_series(symbol, tf))
    ]  # fmt: skip


def _stats(rows: list[Row]) -> dict[str, Any]:
    rs = [r[7] for r in rows if r[7] is not None]
    if not rs:
        return {"signals": len(rows), "trades": 0}
    pos = sum(x for x in rs if x > 0)
    neg = -sum(x for x in rs if x < 0)
    eq = peak = dd = 0.0
    for r in sorted((r for r in rows if r[7] is not None), key=lambda r: r[3]):
        eq += r[7] or 0.0
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    wins = [x for x in rs if x > 0]
    losses = [x for x in rs if x <= 0]
    return {
        "signals": len(rows),
        "trades": len(rs),
        "win": round(len(wins) / len(rs), 3),
        "E": round(statistics.mean(rs), 3),
        "PF": round(pos / neg, 2) if neg else None,
        "avg_win_R": round(statistics.mean(wins), 2) if wins else 0,
        "avg_loss_R": round(statistics.mean(losses), 2) if losses else 0,
        "total_R": round(sum(rs), 1),
        "max_dd_R": round(dd, 1),
    }


def report(workers: int = 4) -> dict[str, Any]:
    symbols = [m.symbol for m in load_universe()]
    jobs = [(n, s, tf) for n in ("4.2", "4.3") for s in symbols for tf in TIMEFRAMES]
    with ProcessPoolExecutor(workers) as ex:
        rows = [r for part in ex.map(_job, jobs) for r in part]
    out: dict[str, Any] = {}
    for name in ("4.2", "4.3"):
        for w, (lo, hi) in WINDOWS.items():
            rs = [r for r in rows if r[0] == name and lo <= r[3] < hi]
            days = (hi - lo) / 86400
            d = _stats(rs)
            d["per_day"] = round(len(rs) / days, 2)
            d["per_week"] = round(7 * len(rs) / days, 1)
            d["by_tf"] = {tf: _stats([r for r in rs if r[2] == tf]) for tf in TIMEFRAMES}
            d["by_side"] = {sd: _stats([r for r in rs if r[4] == sd]) for sd in ("long", "short")}
            d["by_family"] = {f: _stats([r for r in rs if r[6] == f]) for f in {r[6] for r in rs}}
            if name == "4.3":
                d["by_tier"] = {
                    t: _stats([r for r in rs if tier(r[5]) == t]) for t in ("A+", "A", "B", "C")
                }
                d["tiers_AplusA"] = _stats([r for r in rs if r[5] >= 75])
            cnt = collections.Counter(r[1] for r in rs if r[7] is not None)
            d["top_symbol_share"] = round(max(cnt.values()) / sum(cnt.values()), 3) if cnt else None
            symbol_days = {(r[1], (r[3] - lo) // 86400) for r in rs}
            d["symbol_days_with_signal"] = round(len(symbol_days) / (len(symbols) * days), 3)
            live = {
                h for r in rs for h in range(r[3] // 3600, max(r[3], r[8]) // 3600 + 1)
            }  # hours with at least one open opportunity anywhere in the universe
            d["hours_with_live_opportunity"] = round(
                len([h for h in live if lo // 3600 <= h < hi // 3600]) / int(days * 24), 3
            )
            out[f"{name}/{w}"] = d
    return out


def main() -> None:
    data = report()
    text = json.dumps(data, indent=1)
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as fh:
            fh.write(text)
    for key, d in data.items():
        print(
            f"{key:16s} signals/day={d['per_day']:5.2f} trades={d.get('trades')} "
            f"win={d.get('win')} E={d.get('E')} PF={d.get('PF')} DD={d.get('max_dd_R')}"
        )


if __name__ == "__main__":
    main()
