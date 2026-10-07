"""Fast float loading, quality audit and complete-bucket aggregation of research candles.

Cleaning rules (documented in docs/research-ltf.md §7):
* rows are never modified or synthesised; duplicates cannot exist (store primary key);
* a candle with impossible OHLC (high < max(open, close), low > min(open, close), a
  non-positive price) or negative volume is DROPPED and counted, and the hole it leaves is
  treated like any other gap;
* an "extreme" candle (range > 25x the trailing median range and > 8% of price) is KEPT and
  only counted. Inspection showed every such candle in the universe is a real, continuous
  market event (e.g. the 2025-10-10 liquidation cascade, the 2024-12-05 BTC flash drop);
  dropping them would delete the worst stop-outs and bias results upward;
* gaps are never filled. Aggregated candles (10m/15m/30m/1h) are built only from complete
  buckets (every child present), otherwise the bucket is skipped;
* the strategy restarts its warm-up after any gap longer than 3 candles (see strategy.py).
"""

from __future__ import annotations

import sqlite3
from bisect import insort
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

from app.research.store import STORE_PATH

MINUTE_MS = 60_000

# Pre-registered split boundaries (docs/research-ltf.md §2), UTC.
DEV_END_MS = 1775001600000  # 2026-04-01 00:00 (development < this)
VAL_END_MS = 1782864000000  # 2026-07-01 00:00 (validation < this; holdout >= this)
HOLDOUT_START_MS = VAL_END_MS


class HoldoutLockedError(RuntimeError):
    """Raised when research code would read holdout candles without the explicit unlock."""


TF_MS = {
    "1m": MINUTE_MS,
    "5m": 5 * MINUTE_MS,
    "10m": 10 * MINUTE_MS,
    "15m": 15 * MINUTE_MS,
    "30m": 30 * MINUTE_MS,
    "1h": 60 * MINUTE_MS,
}


@dataclass(slots=True)
class Series:
    """Columnar closed candles of one symbol/timeframe (open time in ms)."""

    symbol: str
    timeframe: str
    t: list[int] = field(default_factory=list)
    o: list[float] = field(default_factory=list)
    h: list[float] = field(default_factory=list)
    lo: list[float] = field(default_factory=list)
    c: list[float] = field(default_factory=list)
    v: list[float] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.t)

    @property
    def step(self) -> int:
        return TF_MS[self.timeframe]

    def close_time(self, i: int) -> int:
        return self.t[i] + self.step

    def append(self, t: int, o: float, h: float, lo: float, c: float, v: float) -> None:
        self.t.append(t)
        self.o.append(o)
        self.h.append(h)
        self.lo.append(lo)
        self.c.append(c)
        self.v.append(v)


@dataclass(slots=True)
class Quality:
    symbol: str
    timeframe: str
    rows: int = 0
    kept: int = 0
    malformed: int = 0
    extreme: int = 0
    gaps: int = 0
    missing_candles: int = 0
    longest_gap_candles: int = 0
    zero_volume: int = 0
    first_ms: int | None = None
    last_ms: int | None = None

    def as_dict(self) -> dict[str, object]:
        return {k: getattr(self, k) for k in self.__slots__}


def load(
    symbol: str,
    timeframe: str,
    path: Path = STORE_PATH,
    end_ms: int | None = HOLDOUT_START_MS,
    *,
    unlock_holdout: bool = False,
) -> tuple[Series, Quality]:
    """Load one native series (1m or 5m) as floats, applying the cleaning rules.

    By default only candles BEFORE the holdout are returned. Reading the holdout requires
    `unlock_holdout=True` (used once, by the frozen-candidate holdout evaluation).
    """
    if (end_ms is None or end_ms > HOLDOUT_START_MS) and not unlock_holdout:
        raise HoldoutLockedError("holdout candles are locked until the candidate is frozen")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        sql = (
            "SELECT open_ms, open, high, low, close, volume FROM candles "
            "WHERE symbol = ? AND timeframe = ?"
        )
        args: tuple[object, ...] = (symbol, timeframe)
        if end_ms is not None:
            sql += " AND open_ms < ?"
            args += (end_ms,)
        rows = con.execute(sql + " ORDER BY open_ms", args).fetchall()
    finally:
        con.close()
    q = Quality(symbol, timeframe, rows=len(rows))
    s = Series(symbol, timeframe)
    ranges: deque[float] = deque(maxlen=500)
    window: list[float] = []
    step = TF_MS[timeframe]
    for t, o_, h_, l_, c_, v_ in rows:
        o, h, lo, c, v = float(o_), float(h_), float(l_), float(c_), float(v_)
        if min(o, h, lo, c) <= 0 or h < max(o, c) or lo > min(o, c) or v < 0:
            q.malformed += 1
            continue
        rng = h - lo
        if len(window) >= 100:
            median = window[len(window) // 2]
            if median > 0 and rng > 25 * median and rng > 0.08 * c:
                q.extreme += 1
        if len(ranges) == ranges.maxlen:
            old = ranges[0]
            window.pop(_index(window, old))
        ranges.append(rng)
        insort(window, rng)
        if v == 0:
            q.zero_volume += 1
        if s.t:
            missing = (t - s.t[-1]) // step - 1
            if missing > 0:
                q.gaps += 1
                q.missing_candles += missing
                q.longest_gap_candles = max(q.longest_gap_candles, missing)
        s.append(t, o, h, lo, c, v)
    q.kept = len(s)
    q.first_ms = s.t[0] if s.t else None
    q.last_ms = s.t[-1] if s.t else None
    return s, q


def _index(sorted_list: list[float], value: float) -> int:
    from bisect import bisect_left

    return bisect_left(sorted_list, value)


def aggregate(base: Series, timeframe: str) -> Series:
    """Complete-bucket aggregation (every child present) of a 1m/5m series."""
    step, child = TF_MS[timeframe], base.step
    if step % child:
        raise ValueError(f"cannot aggregate {base.timeframe} into {timeframe}")
    need = step // child
    out = Series(base.symbol, timeframe)
    i, n = 0, len(base)
    while i < n:
        bucket = base.t[i] - base.t[i] % step
        j = i
        while j < n and base.t[j] - base.t[j] % step == bucket:
            j += 1
        if j - i == need:
            out.append(
                bucket,
                base.o[i],
                max(base.h[i:j]),
                min(base.lo[i:j]),
                base.c[j - 1],
                sum(base.v[i:j]),
            )
        i = j
    return out
