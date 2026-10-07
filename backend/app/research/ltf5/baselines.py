"""Simple baselines on the same simulator and costs (docs/research-ltf.md §4).

B1 simple trend continuation: EMA20 > EMA50 and a close above the prior 20-candle high
   (mirrored for shorts); stop 1.5 ATR; single 2R target; 48-candle time stop.
B2 analysis directional bias: the moment trend (EMA20 vs EMA50) and main swing structure
   (direction of the last close beyond a confirmed fractal swing) newly agree; stop 1.5 ATR;
   2R target.
"""

from __future__ import annotations

from app.research.ltf5.data import Series
from app.research.ltf5.strategy import ATR_N, EMA_FAST, EMA_SLOW, WARMUP, Candidate, Plan, _Ema


def _cand(i: int, s: Series, side: int, atr: float) -> Candidate:
    entry = s.c[i]
    risk = 1.5 * atr
    tp = entry + side * 2 * risk
    plan = Plan(entry, entry - side * risk, risk, (tp, tp, tp))
    return Candidate(
        i=i,
        time=s.t[i] + s.step,
        side=side,
        atr=atr,
        market=plan,
        limit=plan,
        ctx_dir=side,
        disp=False,
        candle=False,
        sweep=False,
        vol=False,
        volband=False,
        ext_ok=True,
        too_wide=False,
        hour=((s.t[i] + s.step) // 3_600_000) % 24,
        atr_pct=50.0,
        ctx_strength=0.0,
    )


def b1_trend(s: Series) -> list[Candidate]:
    fast, slow = _Ema(EMA_FAST), _Ema(EMA_SLOW)
    atr: float | None = None
    out = []
    for i in range(len(s)):
        tr = (
            s.h[i] - s.lo[i]
            if i == 0
            else max(s.h[i] - s.lo[i], abs(s.h[i] - s.c[i - 1]), abs(s.lo[i] - s.c[i - 1]))
        )
        atr = tr if atr is None else atr + (tr - atr) / ATR_N
        ef, es = fast.update(s.c[i]), slow.update(s.c[i])
        if i < WARMUP:
            continue
        hi20, lo20 = max(s.h[i - 20 : i]), min(s.lo[i - 20 : i])
        prev_in = lo20 <= s.c[i - 1] <= hi20
        if ef > es and s.c[i] > hi20 and prev_in:
            out.append(_cand(i, s, 1, atr))
        elif ef < es and s.c[i] < lo20 and prev_in:
            out.append(_cand(i, s, -1, atr))
    return out


def b2_bias(s: Series) -> list[Candidate]:
    fast, slow = _Ema(EMA_FAST), _Ema(EMA_SLOW)
    atr: float | None = None
    swing_hi = swing_lo = None
    structure = 0
    agreed = 0
    out = []
    for i in range(len(s)):
        tr = (
            s.h[i] - s.lo[i]
            if i == 0
            else max(s.h[i] - s.lo[i], abs(s.h[i] - s.c[i - 1]), abs(s.lo[i] - s.c[i - 1]))
        )
        atr = tr if atr is None else atr + (tr - atr) / ATR_N
        ef, es = fast.update(s.c[i]), slow.update(s.c[i])
        j = i - 2
        if j >= 2:
            if s.h[j] > max(s.h[j - 1], s.h[j - 2]) and s.h[j] >= max(s.h[j + 1], s.h[j + 2]):
                swing_hi = s.h[j]
            if s.lo[j] < min(s.lo[j - 1], s.lo[j - 2]) and s.lo[j] <= min(s.lo[j + 1], s.lo[j + 2]):
                swing_lo = s.lo[j]
        if swing_hi is not None and s.c[i] > swing_hi:
            structure = 1
        elif swing_lo is not None and s.c[i] < swing_lo:
            structure = -1
        trend = 1 if ef > es else -1
        now = trend if trend == structure else 0
        if i >= WARMUP and now != 0 and now != agreed:
            out.append(_cand(i, s, now, atr))
        agreed = now
    return out
