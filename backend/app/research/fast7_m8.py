"""Phase 7 Stage 2: M8 cross-asset lead-lag (5m) trade-plan simulation (docs/research-fast7.md §7).

Event (closed 5m candles, causal): BTC candle return >= 2 x ATR(BTC) in direction d while the
alt's same-candle move in d is < 0.5 x ATR(alt). Trade the alt in d.

    python -m app.research.fast7_m8 dev          # development: 4 pre-registered variants
    python -m app.research.fast7_m8 validate     # validation segment, the frozen pick only
    python -m app.research.fast7_m8 walkforward  # quarterly folds
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, replace
from typing import Any

from app.research.ltf5 import data, metrics, sim
from app.research.ltf5.data import DEV_END_MS, HOLDOUT_START_MS, VAL_END_MS, Series
from app.research.ltf5.run import FOLDS, OUT, members
from app.research.ltf5.strategy import Candidate, Plan
from app.scalp6.indicators import Atr

LEADER = "BTCUSDT"
IMPULSE_ATR = 2.0
LAG_ATR = 0.5


@dataclass(frozen=True, slots=True)
class Variant:
    plan: str  # V1 | V2
    entry: str  # market | limit

    @property
    def key(self) -> str:
        return f"{self.plan}/{self.entry}"


VARIANTS = tuple(Variant(p, e) for p in ("V1", "V2") for e in ("market", "limit"))


def _atr(s: Series) -> list[float]:
    a = Atr(14)
    return [a.update(s.h[i], s.lo[i], s.c[i]) for i in range(len(s))]


def events(alt: Series, btc: Series, btc_atr: list[float]) -> list[tuple[int, int, float]]:
    """(alt candle index, direction, alt ATR) for every lead-lag event (causal)."""
    idx = {t: j for j, t in enumerate(btc.t)}
    alt_atr = _atr(alt)
    out = []
    for i in range(300, len(alt)):
        j = idx.get(alt.t[i])
        if j is None or j < 300:
            continue
        move = btc.c[j] - btc.o[j]
        if abs(move) < IMPULSE_ATR * btc_atr[j]:
            continue
        d = 1 if move > 0 else -1
        if d * (alt.c[i] - alt.o[i]) >= LAG_ATR * alt_atr[i]:
            continue
        out.append((i, d, alt_atr[i]))
    return out


def candidate(alt: Series, i: int, d: int, atr: float, v: Variant) -> Candidate:
    c = alt.c[i]
    if v.plan == "V1":
        stop = c - d * 1.5 * atr
    else:
        ext = min(alt.lo[i - 2 : i + 1]) if d == 1 else max(alt.h[i - 2 : i + 1])
        stop = ext - d * 0.2 * atr
        if d * (c - stop) < 0.5 * atr:
            stop = c - d * 0.5 * atr

    def plan(entry: float) -> Plan:
        r = d * (entry - stop)
        return Plan(entry, stop, r, (entry + d * r, entry + d * 2 * r, entry + d * 3 * r))

    close_ms = alt.t[i] + alt.step
    return Candidate(
        i=i, time=close_ms, side=d, atr=atr, market=plan(c), limit=plan(c - d * 0.25 * atr),
        ctx_dir=d, disp=False, candle=False, sweep=False, vol=False, volband=False, ext_ok=True,
        too_wide=False, hour=(close_ms // 3_600_000) % 24, atr_pct=50.0, ctx_strength=0.0,
    )  # fmt: skip


def run_variant(
    markets: list[tuple[Series, float, list[tuple[int, int, float]]]],
    v: Variant,
    start: int,
    end: int,
) -> tuple[list[sim.Trade], int]:
    cfg = sim.Config(
        ctx=False, floor=1.0, limit=v.entry == "limit", time_stop=5 if v.plan == "V1" else 15
    )
    out: list[sim.Trade] = []
    missed = 0
    for alt, tick, evs in markets:
        busy = -1
        for i, d, atr in evs:
            t = alt.t[i] + alt.step
            if t < start or t >= end or i <= busy:
                continue
            tr = sim.simulate(alt, candidate(alt, i, d, atr, v), cfg, tick)
            if tr is None:
                missed += 1
                continue
            out.append(tr)
            busy = tr.exit_index
    return out, missed


def load(unlock: bool = False) -> list[tuple[Series, float, list[tuple[int, int, float]]]]:
    end = None if unlock else HOLDOUT_START_MS
    btc, _ = data.load(LEADER, "5m", end_ms=end, unlock_holdout=unlock)
    btc_atr = _atr(btc)
    out = []
    for sym, tick in members():
        if sym == LEADER:
            continue
        alt, _ = data.load(sym, "5m", end_ms=end, unlock_holdout=unlock)
        out.append((alt, tick, events(alt, btc, btc_atr)))
    return out


def report(trades: list[sim.Trade], days: float) -> dict[str, Any]:
    r = metrics.summary(trades, days, ci=True)
    r["long"] = metrics.summary([t for t in trades if t.side == 1]).get("net_e")
    r["short"] = metrics.summary([t for t in trades if t.side == -1]).get("net_e")
    r["per_symbol"] = {
        k: (v.get("trades"), v.get("net_e"))
        for k, v in metrics.group(trades, lambda t: t.symbol).items()
    }
    return r


def cmd_dev() -> dict[str, Any]:
    markets = load()
    first = min(a.t[0] for a, _, _ in markets)
    days = (DEV_END_MS - first) / metrics.DAY_MS
    res: dict[str, Any] = {}
    for v in VARIANTS:
        tr, missed = run_variant(markets, v, 0, DEV_END_MS)
        r = report(tr, days)
        r["missed_entries"] = missed
        res[v.key] = r
        print(
            f"  {v.key:10} n={r.get('trades')} win={r.get('win_rate')} gross={r.get('gross_e')} "
            f"after_fee={r.get('after_fee_e')} net={r.get('net_e')} high={r.get('net_high_e')} "
            f"pf={r.get('pf')} dd={r.get('max_dd')} /day={r.get('per_day')} missed={missed} "
            f"ci90={r.get('ci90')} L={r.get('long')} S={r.get('short')}"
        )
    ranked = sorted(
        (v for v in VARIANTS if res[v.key].get("trades", 0) >= 300),
        key=lambda v: -res[v.key]["net_e"],
    )
    pick = None
    for v in ranked:
        e = res[v.key]["net_e"]
        if e < 0.03 or (res[v.key].get("pf") or 0) < 1.05:
            break
        neigh = [
            replace(v, entry="limit" if v.entry == "market" else "market"),
            replace(v, plan="V2" if v.plan == "V1" else "V1"),
        ]
        if all(res[n.key].get("trades") and res[n.key]["net_e"] > 0 for n in neigh):
            pick = v.key
            break
    out = {"segment": "dev", "days": round(days, 1), "results": res, "pick": pick}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fast7_m8_dev.json").write_text(json.dumps(out, indent=1, default=str))
    print(
        "  G1 pick:",
        pick or "NONE (no variant meets net E >= +0.03, PF >= 1.05, n >= 300, plateau)",
    )
    for k, r in res.items():
        print(f"   {k} per symbol:", r["per_symbol"])
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["dev"])
    p.parse_args()
    cmd_dev()


if __name__ == "__main__":
    main()

__all__ = ["FOLDS", "VAL_END_MS"]
