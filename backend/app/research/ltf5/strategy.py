"""LTF-5 candidate generation: HTF-aligned pullback continuation with a structural trigger.

One causal pass over an execution series (1m/5m/10m) records every raw trigger with all
component flags, so research configurations are cheap filters over the same candidates.

Causality (tested in tests/research/test_ltf5.py):
* only CLOSED candles are used; a decision at candle i uses candles <= i only;
* a fractal swing (n = 2) at candle j is known only from candle j + 2 on;
* a context candle is used only once its close time <= the execution candle's close time;
* after a gap of more than 3 candles the warm-up restarts (no trigger for WARMUP candles).
"""

from __future__ import annotations

from bisect import bisect_left, insort
from collections import deque
from dataclasses import dataclass

from app.research.ltf5.data import Series

EMA_FAST, EMA_SLOW, ATR_N = 20, 50, 14
WARMUP = 120
PULLBACK_WINDOW = 10
FRACTAL = 2
MAX_GAP_CANDLES = 3
CTX_WARMUP = 60
ATR_PCT_WINDOW = 500


@dataclass(frozen=True, slots=True)
class Plan:
    entry: float
    stop: float
    risk: float
    tp: tuple[float, float, float]


@dataclass(frozen=True, slots=True)
class Candidate:
    i: int  # execution candle index of the trigger (closed)
    time: int  # trigger candle CLOSE time (ms)
    side: int  # +1 long, -1 short
    atr: float
    market: Plan  # enter at the trigger close
    limit: Plan  # limit at the trigger-candle midpoint
    ctx_dir: int  # +1 / -1 / 0 (no clear context or context unavailable)
    disp: bool  # trigger body >= 0.5 ATR
    candle: bool  # close in the outer third of the range
    sweep: bool  # pullback swept a prior swing extreme and closed back
    vol: bool  # relative volume >= 1
    volband: bool  # ATR percentile within 10..90
    ext_ok: bool  # entry <= 2.5 ATR from EMA20
    too_wide: bool  # structural risk > 4 ATR (rejected)
    hour: int  # UTC hour of the trigger close
    atr_pct: float  # ATR percentile (0..100)
    ctx_strength: float  # |EMA20 - EMA50| / ATR on the context timeframe

    def flags(self) -> dict[str, bool]:
        return {
            "ctx": self.ctx_dir == self.side,
            "disp": self.disp,
            "candle": self.candle,
            "sweep": self.sweep,
            "vol": self.vol,
            "volband": self.volband,
            "ext": self.ext_ok,
        }

    def score(self) -> float:
        """«قوة توافق شروط الاستراتيجية»: share of satisfied components, 0..100.

        Not a probability of success.
        """
        f = self.flags()
        return round(100 * sum(f.values()) / len(f), 1)


class _Ema:
    __slots__ = ("k", "value")

    def __init__(self, n: int) -> None:
        self.k = 2 / (n + 1)
        self.value: float | None = None

    def update(self, x: float) -> float:
        self.value = x if self.value is None else self.value + self.k * (x - self.value)
        return self.value


class Context:
    """Higher-timeframe direction from closed context candles."""

    def __init__(self, series: Series) -> None:
        self.s = series
        self.k = 0
        self.fast, self.slow = _Ema(EMA_FAST), _Ema(EMA_SLOW)
        self.slow_hist: deque[float] = deque(maxlen=6)
        self.atr: float | None = None
        self.count = 0
        self.last_close_time: int | None = None
        self.last_close = 0.0

    def advance(self, until_close_ms: int) -> None:
        s, step = self.s, self.s.step
        while self.k < len(s) and s.t[self.k] + step <= until_close_ms:
            i = self.k
            if self.last_close_time is not None and s.t[i] - self.last_close_time > 3 * step:
                self.count = 0  # context gap: re-warm
            c = s.c[i]
            tr = s.h[i] - s.lo[i]
            if i > 0:
                tr = max(tr, abs(s.h[i] - s.c[i - 1]), abs(s.lo[i] - s.c[i - 1]))
            self.atr = tr if self.atr is None else self.atr + (tr - self.atr) / ATR_N
            self.fast.update(c)
            self.slow_hist.append(self.slow.update(c))
            self.count += 1
            self.last_close_time = s.t[i] + step
            self.last_close = c
            self.k += 1

    def direction(self, now_close_ms: int) -> tuple[int, float]:
        if (
            self.count < CTX_WARMUP
            or self.last_close_time is None
            or now_close_ms - self.last_close_time > 2 * self.s.step
            or self.fast.value is None
            or self.slow.value is None
            or not self.atr
        ):
            return 0, 0.0
        fast, slow = self.fast.value, self.slow.value
        slope = slow - self.slow_hist[0]
        strength = abs(fast - slow) / self.atr
        if fast > slow and slope > 0 and self.last_close > slow:
            return 1, strength
        if fast < slow and slope < 0 and self.last_close < slow:
            return -1, strength
        return 0, strength


def _plan(side: int, entry: float, stop: float, atr: float, swings: list[float]) -> Plan:
    risk = side * (entry - stop)
    if risk < 0.5 * atr:
        stop = entry - side * 0.5 * atr
        risk = 0.5 * atr
    tp1, tp2 = entry + side * risk, entry + side * 2 * risk
    # TP3: nearest opposing confirmed swing beyond 2R (within 6R), else 3R.
    beyond = [p for p in swings if side * (p - tp2) > 0 and side * (p - entry) <= 6 * risk]
    tp3 = min(beyond, key=lambda p: side * (p - entry)) if beyond else entry + side * 3 * risk
    return Plan(entry, stop, risk, (tp1, tp2, tp3))


def candidates(exec_s: Series, ctx_s: Series | None) -> list[Candidate]:
    """All raw triggers of one execution series (causal, closed candles only)."""
    n = len(exec_s)
    t, o, h, lo, c, v = exec_s.t, exec_s.o, exec_s.h, exec_s.lo, exec_s.c, exec_s.v
    step = exec_s.step
    fast, slow = _Ema(EMA_FAST), _Ema(EMA_SLOW)
    atr: float | None = None
    vol_win: deque[float] = deque(maxlen=20)
    atr_hist: deque[float] = deque(maxlen=ATR_PCT_WINDOW)
    atr_sorted: list[float] = []
    ctx = Context(ctx_s) if ctx_s is not None else None
    swing_hi: list[tuple[int, float]] = []  # (pivot index, price), confirmed
    swing_lo: list[tuple[int, float]] = []
    touch_long: int | None = None  # last candle that pulled back to EMA20 in an uptrend
    touch_short: int | None = None
    sweep_long_at: int | None = None
    sweep_short_at: int | None = None
    warm = 0
    out: list[Candidate] = []
    for i in range(n):
        if i and t[i] - t[i - 1] > (MAX_GAP_CANDLES + 1) * step:
            warm = 0
            touch_long = touch_short = None
            sweep_long_at = sweep_short_at = None
        warm += 1
        tr = h[i] - lo[i]
        if i:
            tr = max(tr, abs(h[i] - c[i - 1]), abs(lo[i] - c[i - 1]))
        atr = tr if atr is None else atr + (tr - atr) / ATR_N
        ef, es = fast.update(c[i]), slow.update(c[i])
        if len(atr_hist) == atr_hist.maxlen:
            atr_sorted.pop(bisect_left(atr_sorted, atr_hist[0]))
        atr_hist.append(atr)
        insort(atr_sorted, atr)
        rel_vol = v[i] / (sum(vol_win) / len(vol_win)) if vol_win and sum(vol_win) > 0 else 0.0
        vol_win.append(v[i])
        # Fractal swing at j = i - 2 becomes known now (needs candles j+1, j+2 closed).
        j = i - FRACTAL
        if j >= FRACTAL and warm > 2 * FRACTAL:
            if all(h[j] > h[j - d] for d in (1, 2)) and all(h[j] >= h[j + d] for d in (1, 2)):
                swing_hi.append((j, h[j]))
            if all(lo[j] < lo[j - d] for d in (1, 2)) and all(lo[j] <= lo[j + d] for d in (1, 2)):
                swing_lo.append((j, lo[j]))
        close_ms = t[i] + step
        if ctx is not None:
            ctx.advance(close_ms)
        if warm < WARMUP or not atr:
            continue
        # Pullback bookkeeping (value = EMA20; invalid beyond EMA50 by more than 1 ATR).
        if ef > es and lo[i] <= ef:
            touch_long = i
        if ef < es and h[i] >= ef:
            touch_short = i
        if touch_long is not None and c[i] < es - atr:
            touch_long = None
        if touch_short is not None and c[i] > es + atr:
            touch_short = None
        if swing_lo and lo[i] < swing_lo[-1][1] < c[i]:
            sweep_long_at = i
        if swing_hi and h[i] > swing_hi[-1][1] > c[i]:
            sweep_short_at = i
        ctx_dir, ctx_strength = ctx.direction(close_ms) if ctx is not None else (0, 0.0)
        pct = 100 * bisect_left(atr_sorted, atr) / max(1, len(atr_sorted) - 1)
        for side in (1, -1):
            touch = touch_long if side == 1 else touch_short
            stack = ef > es if side == 1 else ef < es
            pivots = swing_hi if side == 1 else swing_lo
            if not stack or touch is None or i - touch > PULLBACK_WINDOW or not pivots:
                continue
            level = pivots[-1][1]
            if not (side * (c[i] - level) > 0 and side * (c[i - 1] - level) <= 0):
                continue
            window = range(max(0, i - PULLBACK_WINDOW), i + 1)
            extreme = min(lo[k] for k in window) if side == 1 else max(h[k] for k in window)
            stop = extreme - side * 0.1 * atr
            too_wide = side * (c[i] - stop) > 4 * atr
            targets = [p for _, p in (swing_hi if side == 1 else swing_lo)[-30:]]
            mid = (h[i] + lo[i]) / 2
            rng = h[i] - lo[i]
            loc = (c[i] - lo[i]) / rng if rng > 0 else 0.5
            swept_at = sweep_long_at if side == 1 else sweep_short_at
            out.append(
                Candidate(
                    i=i,
                    time=close_ms,
                    side=side,
                    atr=atr,
                    market=_plan(side, c[i], stop, atr, targets),
                    limit=_plan(side, mid, stop, atr, targets),
                    ctx_dir=ctx_dir,
                    disp=abs(c[i] - o[i]) >= 0.5 * atr,
                    candle=loc >= 2 / 3 if side == 1 else loc <= 1 / 3,
                    sweep=swept_at is not None and i - swept_at <= PULLBACK_WINDOW,
                    vol=rel_vol >= 1.0,
                    volband=10 <= pct <= 90,
                    ext_ok=side * (c[i] - ef) <= 2.5 * atr,
                    too_wide=too_wide,
                    hour=(close_ms // 3_600_000) % 24,
                    atr_pct=pct,
                    ctx_strength=ctx_strength,
                )
            )
            if side == 1:
                touch_long = None  # a pullback produces at most one trigger
            else:
                touch_short = None
    return out
