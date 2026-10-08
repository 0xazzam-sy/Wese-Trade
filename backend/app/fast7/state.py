"""Market-state engine (Phase 7, level 1 of the hierarchy).

UPTREND / DOWNTREND / RANGE / COMPRESSION / EXPANSION / TRANSITION from closed candles:
ADX(14) trend strength, EMA ordering + slope, swing structure, Bollinger-width percentile,
ATR percentile and the trailing 60-candle range width (ATR units).

Priority: EXPANSION > COMPRESSION > UPTREND / DOWNTREND > RANGE > TRANSITION.
"""

from __future__ import annotations

import math
from collections import deque

from app.scalp6.indicators import RollingPercentile

RANGE_WINDOW = 60
STATE_AR = {
    "UPTREND": "اتجاه صاعد",
    "DOWNTREND": "اتجاه هابط",
    "RANGE": "نطاق عرضي",
    "COMPRESSION": "انضغاط",
    "EXPANSION": "توسع وتذبذب",
    "TRANSITION": "مرحلة انتقالية",
}


class Adx:
    """Wilder ADX(n), incremental."""

    __slots__ = ("adx", "count", "dm_m", "dm_p", "n", "prev", "tr")

    def __init__(self, n: int = 14) -> None:
        self.n = n
        self.tr = self.dm_p = self.dm_m = 0.0
        self.adx = 0.0
        self.prev: tuple[float, float, float] | None = None
        self.count = 0

    def update(self, h: float, lo: float, c: float) -> float:
        if self.prev is not None:
            ph, pl, pc = self.prev
            up, down = h - ph, pl - lo
            dm_p = up if up > down and up > 0 else 0.0
            dm_m = down if down > up and down > 0 else 0.0
            tr = max(h - lo, abs(h - pc), abs(lo - pc))
            n = self.n
            self.tr += (tr - self.tr) / n
            self.dm_p += (dm_p - self.dm_p) / n
            self.dm_m += (dm_m - self.dm_m) / n
            if self.tr > 0:
                di_p, di_m = 100 * self.dm_p / self.tr, 100 * self.dm_m / self.tr
                dx = 100 * abs(di_p - di_m) / (di_p + di_m) if di_p + di_m > 0 else 0.0
                self.adx += (dx - self.adx) / n
            self.count += 1
        self.prev = (h, lo, c)
        return self.adx


class StateTracker:
    def __init__(self) -> None:
        self.adx = Adx(14)
        self.closes: deque[float] = deque(maxlen=20)
        self.highs: deque[float] = deque(maxlen=RANGE_WINDOW)
        self.lows: deque[float] = deque(maxlen=RANGE_WINDOW)
        self.bbw_pct = RollingPercentile(300)
        self.history: deque[str] = deque(maxlen=12)
        self.state = "TRANSITION"
        self.bbw = 50.0
        self.range_hi = self.range_lo = 0.0
        self.range_atr = 0.0

    def reset(self) -> None:
        self.__init__()  # type: ignore[misc]

    def update(
        self,
        h: float,
        lo: float,
        c: float,
        atr: float,
        atr_pct: float,
        ema: tuple[float, float, float],
        ema_mid_slope: float,
        structure: int,
    ) -> str:
        adx = self.adx.update(h, lo, c)
        self.closes.append(c)
        self.highs.append(h)
        self.lows.append(lo)
        n = len(self.closes)
        mean = sum(self.closes) / n
        sd = math.sqrt(sum((x - mean) ** 2 for x in self.closes) / n) if n > 1 else 0.0
        self.bbw = self.bbw_pct.update(sd / mean if mean else 0.0)
        self.range_hi, self.range_lo = max(self.highs), min(self.lows)
        self.range_atr = (self.range_hi - self.range_lo) / atr if atr else 0.0
        f, m, s = ema
        if not atr or self.adx.count < 30 or n < 20:
            state = "TRANSITION"
        elif (h - lo) >= 2 * atr or (atr_pct >= 90 and self.bbw >= 85):
            state = "EXPANSION"
        elif self.bbw <= 15:
            state = "COMPRESSION"
        elif adx >= 20 and f > m > s and ema_mid_slope > 0 and structure >= 0:
            state = "UPTREND"
        elif adx >= 20 and f < m < s and ema_mid_slope < 0 and structure <= 0:
            state = "DOWNTREND"
        elif adx < 20 and 3 <= self.range_atr <= 10:
            state = "RANGE"
        else:
            state = "TRANSITION"
        self.state = state
        self.history.append(state)
        return state

    def location_in_range(self, c: float) -> float:
        """0 = range low, 1 = range high (trailing 60 candles)."""
        span = self.range_hi - self.range_lo
        return (c - self.range_lo) / span if span > 0 else 0.5

    def was(self, state: str, within: int) -> bool:
        return state in list(self.history)[-within:]
