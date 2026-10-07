"""LTF-5 research runner (docs/research-ltf.md).

    python -m app.research.ltf5.run audit
    python -m app.research.ltf5.run grid --tf 5m          # development only
    python -m app.research.ltf5.run ablate --tf 5m        # development only
    python -m app.research.ltf5.run walkforward --tf 5m   # dev + validation folds
    python -m app.research.ltf5.run validate --tf 5m      # validation segment, frozen pick
    python -m app.research.ltf5.run holdout --tf 5m       # ONCE, after the candidate is frozen

Results are written to data/research/ltf5/*.json (git-ignored) and summarised in the doc.
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from collections.abc import Iterable, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from app.research import universe
from app.research.ltf5 import baselines, data, metrics, sim, strategy
from app.research.ltf5.data import DEV_END_MS, HOLDOUT_START_MS, VAL_END_MS, Series
from app.research.store import RESEARCH_DIR

OUT = RESEARCH_DIR / "ltf5"
CONTEXTS = {"1m": ("5m", "15m"), "5m": ("15m", "1h"), "10m": ("30m", "1h")}
MIN_DEV_TRADES = 300
FOLDS = [  # (test start, test end) UTC ms: 2025-Q3, 2025-Q4, 2026-Q1, 2026-Q2
    (1751328000000, 1759276800000),
    (1759276800000, 1767225600000),
    (1767225600000, 1775001600000),
    (1775001600000, 1782864000000),
]
COMPONENTS = ("ctx", "disp", "candle", "sweep", "vol", "volband", "ext")


def members() -> list[tuple[str, float]]:
    return [(m.symbol, m.tick_size) for m in universe.load()]


class Market:
    """Execution + context series of one symbol for one execution timeframe."""

    def __init__(self, symbol: str, tick: float, tf: str, unlock: bool = False) -> None:
        end = None if unlock else HOLDOUT_START_MS
        base5, q5 = data.load(symbol, "5m", end_ms=end, unlock_holdout=unlock)
        self.quality = [q5.as_dict()]
        if tf == "1m":
            exe, q1 = data.load(symbol, "1m", end_ms=end, unlock_holdout=unlock)
            self.quality.append(q1.as_dict())
        elif tf == "5m":
            exe = base5
        else:
            exe = data.aggregate(base5, tf)
        self.symbol, self.tick, self.tf, self.exe = symbol, tick, tf, exe
        ctx: dict[str, Series] = {}
        for c in CONTEXTS[tf]:
            ctx[c] = base5 if c == "5m" else data.aggregate(base5, c)
        self.cands = {c: strategy.candidates(exe, s) for c, s in ctx.items()}
        self.base = {"B1": baselines.b1_trend(exe), "B2": baselines.b2_bias(exe)}

    def first_ms(self) -> int:
        return self.exe.t[0] if self.exe.t else 0


def grid_configs(tf: str) -> list[tuple[str, sim.Config]]:
    out = []
    for ctx_tf, disp, floor, be, limit in itertools.product(
        CONTEXTS[tf], (False, True), (0.10, 0.20), (False, True), (False, True)
    ):
        out.append((ctx_tf, sim.Config(ctx=True, disp=disp, floor=floor, be=be, limit=limit)))
    return out


def grid_configs_51(tf: str) -> list[tuple[str, sim.Config]]:
    """LTF-5.1 pre-registered grid (docs/research-ltf.md §9)."""
    out = []
    for ctx_tf, time_stop, runner in itertools.product(CONTEXTS[tf], (48, 96), (False, True)):
        cfg = sim.Config(ctx=True, floor=0.10, regime=True, time_stop=time_stop, runner=runner)
        out.append((ctx_tf, cfg))
    return out


ANCHORS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


def cmd_grid51(tf: str) -> dict[str, Any]:
    markets = [Market(s, tick, tf) for s, tick in members()]
    days = span_days(markets, 0, DEV_END_MS)
    results: dict[str, dict[str, Any]] = {}
    verdict: dict[str, Any] = {"pass": []}
    for c, cfg in grid_configs_51(tf):
        trades = trades_for(markets, c, cfg, 0, DEV_END_MS)
        r = metrics.summary(trades, days)
        anchor = [t for t in trades if t.symbol in ANCHORS]
        other = [t for t in trades if t.symbol not in ANCHORS]
        r["anchors"] = metrics.summary(anchor)
        r["others"] = metrics.summary(other)
        results[label(c, cfg)] = r
        ok = (
            r.get("trades", 0) >= MIN_DEV_TRADES
            and r["net_e"] >= 0.05
            and r["gross_e"] >= 0.10
            and r["anchors"].get("net_e", -1) > 0
            and r["others"].get("net_e", -1) > 0
        )
        if ok:
            verdict["pass"].append(label(c, cfg))
        print(
            f"  {label(c, cfg):80} n={r.get('trades', 0):5} gross={r.get('gross_e', 0):+.3f} "
            f"net={r.get('net_e', 0):+.3f} pf={r.get('pf')} anchors={r['anchors'].get('net_e')} "
            f"others={r['others'].get('net_e')}"
        )
    out = {"tf": tf, "segment": "dev", "iteration": "5.1", "results": results, "verdict": verdict}
    _save(f"{tf}_dev_grid51.json", out)
    print("  5.1 development bar passed by:", verdict["pass"] or "NONE")
    return out


def trades_for(
    markets: Sequence[Market], ctx_tf: str, cfg: sim.Config, start: int, end: int
) -> list[sim.Trade]:
    out: list[sim.Trade] = []
    for m in markets:
        out += sim.run(m.exe, m.cands[ctx_tf], cfg, m.tick, start, end)
    return out


def baseline_trades(markets: Sequence[Market], name: str, start: int, end: int) -> list[sim.Trade]:
    cfg = sim.Config(ctx=False, floor=1.0)  # baselines: no cost floor, market entries
    out: list[sim.Trade] = []
    for m in markets:
        out += sim.run(m.exe, m.base[name], cfg, m.tick, start, end)
    return out


def span_days(markets: Sequence[Market], start: int, end: int) -> float:
    first = min(m.first_ms() for m in markets)
    return max(1.0, (end - max(start, first)) / metrics.DAY_MS)


def label(ctx_tf: str, cfg: sim.Config) -> str:
    return f"ctx_tf={ctx_tf} {cfg.key()}"


def neighbours(tf: str, ctx_tf: str, cfg: sim.Config) -> list[tuple[str, sim.Config]]:
    """Configurations that differ from (ctx_tf, cfg) in exactly one grid dimension."""
    out = [(c, cfg) for c in CONTEXTS[tf] if c != ctx_tf]
    out.append((ctx_tf, replace(cfg, disp=not cfg.disp)))
    out.append((ctx_tf, replace(cfg, floor=0.20 if cfg.floor == 0.10 else 0.10)))
    out.append((ctx_tf, replace(cfg, be=not cfg.be)))
    out.append((ctx_tf, replace(cfg, limit=not cfg.limit)))
    return out


def select(
    tf: str, results: dict[str, dict[str, Any]], configs: Iterable[tuple[str, sim.Config]]
) -> dict[str, Any]:
    """Pre-registered selection: best dev net E (>= 300 trades) whose neighbours hold."""
    ranked = sorted(
        (
            (results[label(c, cfg)]["net_e"], c, cfg)
            for c, cfg in configs
            if results[label(c, cfg)].get("trades", 0) >= MIN_DEV_TRADES
        ),
        key=lambda x: -x[0],
    )
    for e, c, cfg in ranked:
        if e <= 0:
            break
        neigh = [results[label(nc, ncfg)] for nc, ncfg in neighbours(tf, c, cfg)]
        ok = all(n.get("trades", 0) and n["net_e"] > 0 and n["net_e"] >= 0.5 * e for n in neigh)
        if ok:
            return {"pick": label(c, cfg), "ctx_tf": c, "config": asdict(cfg), "plateau": True}
    best = ranked[0] if ranked else None
    return {
        "pick": None,
        "reason": "no configuration with >= 300 dev trades, net E > 0 and a stable plateau",
        "best_unstable": label(best[1], best[2]) if best else None,
    }


def cmd_grid(tf: str, start: int = 0, end: int = DEV_END_MS, tag: str = "dev") -> dict[str, Any]:
    t0 = time.time()
    markets = [Market(s, tick, tf) for s, tick in members()]
    days = span_days(markets, start, end)
    configs = grid_configs(tf)
    results = {
        label(c, cfg): metrics.summary(trades_for(markets, c, cfg, start, end), days)
        for c, cfg in configs
    }
    base = {
        name: metrics.summary(baseline_trades(markets, name, start, end), days)
        for name in ("B1", "B2")
    }
    pick = select(tf, results, configs)
    out = {
        "tf": tf,
        "segment": tag,
        "start": start,
        "end": end,
        "days": round(days, 1),
        "results": results,
        "baselines": base,
        "selection": pick,
        "seconds": round(time.time() - t0, 1),
    }
    _save(f"{tf}_{tag}_grid.json", out)
    print(f"== {tf} {tag} grid ({days:.0f} days, {out['seconds']}s)")
    for k, r in sorted(results.items(), key=lambda kv: -kv[1].get("net_e", -9)):
        print(
            f"  {k:62} n={r.get('trades', 0):5} gross={r.get('gross_e', 0):+.3f} "
            f"net={r.get('net_e', 0):+.3f} pf={r.get('pf')} dd={r.get('max_dd')}"
        )
    for name, r in base.items():
        print(
            f"  baseline {name}: n={r.get('trades')} gross={r.get('gross_e')} net={r.get('net_e')}"
        )
    print("  selection:", json.dumps(pick))
    return out


def _save(name: str, payload: object) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    Path(OUT / name).write_text(json.dumps(payload, indent=1, default=str))


def cmd_audit() -> None:
    rows = []
    for s, _ in members():
        for tf in ("1m", "5m"):
            _, q = data.load(s, tf)
            rows.append(q.as_dict())
            print(json.dumps(q.as_dict()))
    _save("audit.json", rows)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["audit", "grid", "grid51"])
    p.add_argument("--tf", choices=list(CONTEXTS), default="5m")
    a = p.parse_args()
    if a.command == "audit":
        cmd_audit()
    elif a.command == "grid51":
        cmd_grid51(a.tf)
    else:
        cmd_grid(a.tf)


if __name__ == "__main__":
    main()

__all__ = ["DEV_END_MS", "VAL_END_MS", "Market", "cmd_grid"]
