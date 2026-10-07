"""Cost-aware trade simulation for LTF-5 research (docs/research-ltf.md §3)."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.research.ltf5.data import Series
from app.research.ltf5.strategy import Candidate, Plan

TIME_STOP = 48
LIMIT_EXPIRY = 3


@dataclass(frozen=True, slots=True)
class Costs:
    name: str
    taker: float
    maker: float
    slip: float  # per side, market orders
    stop_extra: float  # additional adverse slippage on stop exits


BASE = Costs("base", taker=0.0005, maker=0.0002, slip=0.0002, stop_extra=0.0002)
HIGH = Costs("high", taker=0.0006, maker=0.0003, slip=0.0005, stop_extra=0.0005)


@dataclass(frozen=True, slots=True)
class Config:
    """One research configuration (§5). Flags not listed are not required."""

    ctx: bool = True
    disp: bool = False
    floor: float = 0.20  # cost floor F: skip when round-trip cost > F x risk
    be: bool = False  # move the stop to entry after TP1
    limit: bool = False  # limit at the trigger midpoint instead of market at close
    require: tuple[str, ...] = ()  # extra component flags required (ablation)
    sessions: tuple[int, ...] = ()  # UTC hours excluded (empty = none)

    def key(self) -> str:
        parts = [
            f"ctx={int(self.ctx)}",
            f"disp={int(self.disp)}",
            f"F={self.floor}",
            f"be={int(self.be)}",
            f"entry={'limit' if self.limit else 'market'}",
        ]
        if self.require:
            parts.append("req=" + "+".join(self.require))
        if self.sessions:
            parts.append(f"skip_h={len(self.sessions)}")
        return " ".join(parts)


@dataclass(frozen=True, slots=True)
class Trade:
    symbol: str
    timeframe: str
    side: int
    signal_time: int
    entry_time: int
    exit_time: int
    exit_index: int
    bars: int
    gross_r: float
    fee_r: float  # after fees only
    net_r: float  # after fees + slippage (base)
    net_high_r: float  # after fees + slippage (high stress)
    targets_hit: int
    exit_reason: str
    score: float
    hour: int
    atr_pct: float
    ctx_dir: int
    ctx_strength: float
    risk_pct: float


def round_trip_cost(price: float, tick: float, costs: Costs, market: bool) -> float:
    """Worst-case round trip as a fraction of price (entry + stop exit)."""
    slip = max(costs.slip, tick / price)
    entry = (costs.taker + slip) if market else costs.maker
    return entry + costs.taker + slip + costs.stop_extra


def passes(c: Candidate, cfg: Config) -> bool:
    if c.too_wide:
        return False
    if cfg.ctx and c.ctx_dir != c.side:
        return False
    if cfg.disp and not c.disp:
        return False
    flags = c.flags()
    if any(not flags[name] for name in cfg.require):
        return False
    return not (cfg.sessions and c.hour in cfg.sessions)


def _round(price: float, tick: float, away_from: float, outward: bool) -> float:
    if tick <= 0:
        return price
    q = price / tick
    up = price > away_from
    if outward:
        return (math.ceil(q) if up else math.floor(q)) * tick
    return (math.floor(q) if up else math.ceil(q)) * tick


def simulate(
    s: Series, c: Candidate, cfg: Config, tick: float, costs: Sequence[Costs] = (BASE, HIGH)
) -> Trade | None:
    """Simulate one candidate. None = skipped (cost floor) or never filled (limit)."""
    plan: Plan = c.limit if cfg.limit else c.market
    side = c.side
    entry = plan.entry
    stop = _round(plan.stop, tick, entry, outward=True)  # stop rounded away: more risk
    risk = side * (entry - stop)
    if risk <= 0:
        return None
    if round_trip_cost(entry, tick, costs[0], not cfg.limit) * entry > cfg.floor * risk:
        return None
    tps = [_round(p, tick, entry, outward=False) for p in plan.tp]  # targets rounded inward
    h, lo, o, cl, t = s.h, s.lo, s.o, s.c, s.t
    n = len(s)
    start = c.i + 1
    if cfg.limit:
        filled = None
        for k in range(c.i + 1, min(n, c.i + 1 + LIMIT_EXPIRY)):
            through = lo[k] <= entry - tick if side == 1 else h[k] >= entry + tick
            if through:
                filled = k
                break
            hit_tp1 = h[k] >= tps[0] if side == 1 else lo[k] <= tps[0]
            hit_stop = lo[k] <= stop if side == 1 else h[k] >= stop
            if hit_tp1 or hit_stop:
                return None  # the move left (or failed) before the fill
        if filled is None:
            return None
        start = filled
    exits: list[tuple[float, float, str]] = []
    remaining, hit = 1.0, 0
    live_stop = stop
    j = start
    last = start
    while j < n and remaining > 1e-9:
        last = j
        fill_bar = cfg.limit and j == start
        gap_through = (o[j] <= live_stop) if side == 1 else (o[j] >= live_stop)
        if gap_through and not fill_bar:
            exits.append((remaining, o[j], "stop"))
            remaining = 0
            break
        touched = (lo[j] <= live_stop) if side == 1 else (h[j] >= live_stop)
        if touched:  # stop first when stop and a target share a candle (conservative)
            exits.append((remaining, live_stop, "stop" if hit == 0 else "stop_after_tp"))
            remaining = 0
            break
        if not fill_bar:
            moved = False
            while hit < 3 and ((h[j] >= tps[hit]) if side == 1 else (lo[j] <= tps[hit])):
                frac = 1 / 3 if hit < 2 else remaining
                exits.append((frac, tps[hit], f"tp{hit + 1}"))
                remaining -= frac
                hit += 1
                moved = True
            if moved and cfg.be and hit >= 1:
                live_stop = entry  # applies from the next candle on
        if remaining > 1e-9 and j - start + 1 >= TIME_STOP:
            exits.append((remaining, cl[j], "time"))
            remaining = 0
            break
        j += 1
    if remaining > 1e-9:
        exits.append((remaining, cl[last], "end"))
    gross = sum(f * side * (p - entry) / risk for f, p, _ in exits)
    net_by_cost = []
    fee_only = 0.0
    for idx, cost in enumerate(costs):
        slip = max(cost.slip, tick / entry)
        fees = (cost.maker if cfg.limit else cost.taker) * entry
        slips = 0.0 if cfg.limit else slip * entry
        for f, p, why in exits:
            if why.startswith("tp"):
                fees += f * cost.maker * p
            else:
                fees += f * cost.taker * p
                slips += f * (slip + (cost.stop_extra if why.startswith("stop") else 0)) * p
        if idx == 0:
            fee_only = gross - fees / risk
        net_by_cost.append(gross - (fees + slips) / risk)
    exit_reason = exits[-1][2]
    return Trade(
        symbol=s.symbol,
        timeframe=s.timeframe,
        side=side,
        signal_time=c.time,
        entry_time=t[start - 1] + s.step if not cfg.limit else t[start] + s.step,
        exit_time=t[last] + s.step,
        exit_index=last,
        bars=last - c.i,
        gross_r=gross,
        fee_r=fee_only,
        net_r=net_by_cost[0],
        net_high_r=net_by_cost[-1],
        targets_hit=hit,
        exit_reason=exit_reason,
        score=c.score(),
        hour=c.hour,
        atr_pct=c.atr_pct,
        ctx_dir=c.ctx_dir,
        ctx_strength=c.ctx_strength,
        risk_pct=100 * risk / entry,
    )


def run(
    s: Series, cands: Iterable[Candidate], cfg: Config, tick: float, start_ms: int, end_ms: int
) -> list[Trade]:
    """Sequential trading of one series in [start_ms, end_ms): one position at a time.

    A new trade needs a trigger strictly after the previous trade's exit candle (no
    re-entry on the same setup, no overlapping or contradictory positions).
    """
    trades: list[Trade] = []
    busy_until = -1
    for c in cands:
        if c.time < start_ms or c.time >= end_ms or c.i <= busy_until:
            continue
        if not passes(c, cfg):
            continue
        tr = simulate(s, c, cfg, tick)
        if tr is None:
            continue
        trades.append(tr)
        busy_until = tr.exit_index
    return trades
