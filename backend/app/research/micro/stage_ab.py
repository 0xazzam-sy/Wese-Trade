"""Phase 8 Stage A (feature IC) and Stage B (setup directional edge) on real trade flow.

Pre-registered in docs/research-microscalp.md §5. Inputs are only the exchange trade-archive
5-second buckets (exact aggressor side). Development segment only unless --segment says otherwise;
the holdout is locked in `trades.read_day`.

    python -m app.research.micro.stage_ab run [--segment dev|val] [--tfs 1m,5m,10m]
"""

from __future__ import annotations

import argparse
import json
import math
import time
from array import array
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.fast7.state import StateTracker
from app.research.micro.trades import BUCKET_MS, PER_DAY, day_start_ms, read_day
from app.research.store import RESEARCH_DIR
from app.scalp6.indicators import Atr, Ema, RollingPercentile

OUT = RESEARCH_DIR / "micro" / "results"
SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "HYPEUSDT",
    "NEARUSDT", "UNIUSDT", "PUMPUSDT", "SUIUSDT", "PEPEUSDT", "ARBUSDT",
)  # fmt: skip
LEADER = "BTCUSDT"
TF_BUCKETS = {"1m": 12, "5m": 60, "10m": 120}
HORIZONS_MIN = (1, 5, 10, 30)
LATENCIES_S = (0, 5, 10, 20, 30)
LATENCY_S = 20  # the manual-entry model
WARMUP = 300
WIN = 288
FEATURES = ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8")
SETUPS = ("B-A", "B-B", "B-C", "B-D", "B-E")
# Archive file days (UTC+8): file D covers [D-1 16:00, D 16:00) UTC.
SEGMENTS = {
    "dev": (date(2025, 10, 7), date(2026, 3, 31)),
    "val": (date(2026, 4, 1), date(2026, 6, 30)),
}
HALF_SPLIT_MS = int(datetime(2026, 1, 1, tzinfo=UTC).timestamp() * 1000)
NAN = math.nan


@dataclass
class Buckets:
    start_ms: int
    price: array[float]  # last trade price up to the end of each bucket (forward-filled)
    hi: array[float]
    lo: array[float]
    buy: array[float]
    sell: array[float]
    big_buy: array[float]
    big_sell: array[float]
    n: array[int]
    missing_days: int = 0

    def __len__(self) -> int:
        return len(self.price)

    def px_at(self, k_end: int, offset_s: int) -> float:
        """Last trade price at `offset_s` seconds after the bucket boundary k_end."""
        k = k_end + offset_s * 1000 // BUCKET_MS - 1
        return self.price[k] if 0 <= k < len(self.price) else NAN


def load(symbol: str, first: date, last: date) -> Buckets:
    names = ("price", "hi", "lo", "buy", "sell", "big_buy", "big_sell")
    cols: dict[str, array[Any]] = {k: array("d") for k in names}
    n_col: array[int] = array("i")
    missing = 0
    prev = NAN
    d = first
    while d <= last:
        day = read_day(symbol, d)
        if day is None:
            missing += 1
            nan_day = array("d", [NAN]) * PER_DAY
            zero = array("d", [0.0]) * PER_DAY
            for k in ("price", "hi", "lo"):
                cols[k].extend(nan_day)
            for k in ("buy", "sell", "big_buy", "big_sell"):
                cols[k].extend(zero)
            n_col.extend(array("i", [0]) * PER_DAY)
            prev = NAN
        else:
            last_px = day["last"]
            ff = array("d", [NAN]) * PER_DAY
            for i in range(PER_DAY):
                x = last_px[i]
                if x == x:
                    prev = x
                ff[i] = prev
            cols["price"].extend(ff)
            cols["hi"].extend(array("d", day["high"]))
            cols["lo"].extend(array("d", day["low"]))
            for k, src in (("buy", "buy_vol"), ("sell", "sell_vol"), ("big_buy", "big_buy"),
                           ("big_sell", "big_sell")):  # fmt: skip
                cols[k].extend(array("d", day[src]))
            n_col.extend(
                array("i", [a + b for a, b in zip(day["buy_n"], day["sell_n"], strict=True)])
            )
        d += timedelta(days=1)
    return Buckets(day_start_ms(first), n=n_col, missing_days=missing, **cols)


@dataclass
class Candles:
    m: int  # buckets per candle
    k_end: list[int] = field(default_factory=list)  # bucket index of the candle's close boundary
    o: list[float] = field(default_factory=list)
    h: list[float] = field(default_factory=list)
    lo: list[float] = field(default_factory=list)
    c: list[float] = field(default_factory=list)
    buy: list[float] = field(default_factory=list)
    sell: list[float] = field(default_factory=list)
    bb: list[float] = field(default_factory=list)
    bs: list[float] = field(default_factory=list)
    n: list[int] = field(default_factory=list)
    buy30: list[float] = field(default_factory=list)
    sell30: list[float] = field(default_factory=list)


def minute_candles(b: Buckets) -> Candles:
    out = Candles(12)
    p, hi, lo = b.price, b.hi, b.lo
    for j in range(len(b) // 12):
        s, e = j * 12, j * 12 + 12
        c = p[e - 1]
        o = p[s - 1] if s > 0 else NAN
        if o != o:
            o = c
        hs = [x for x in hi[s:e] if x == x]
        ls = [x for x in lo[s:e] if x == x]
        out.k_end.append(e)
        out.o.append(o)
        out.c.append(c)
        out.h.append(max([*hs, o, c]) if c == c else NAN)
        out.lo.append(min([*ls, o, c]) if c == c else NAN)
        out.buy.append(sum(b.buy[s:e]))
        out.sell.append(sum(b.sell[s:e]))
        out.bb.append(sum(b.big_buy[s:e]))
        out.bs.append(sum(b.big_sell[s:e]))
        out.n.append(sum(b.n[s:e]))
        out.buy30.append(sum(b.buy[e - 6 : e]))
        out.sell30.append(sum(b.sell[e - 6 : e]))
    return out


def aggregate(m1: Candles, f: int) -> Candles:
    if f == 1:
        return m1
    out = Candles(12 * f)
    for j in range(len(m1.c) // f):
        s, e = j * f, j * f + f
        out.k_end.append(m1.k_end[e - 1])
        out.o.append(m1.o[s])
        out.c.append(m1.c[e - 1])
        out.h.append(max(m1.h[s:e]))
        out.lo.append(min(m1.lo[s:e]))
        for name in ("buy", "sell", "bb", "bs", "n"):
            getattr(out, name).append(sum(getattr(m1, name)[s:e]))
        out.buy30.append(m1.buy30[e - 1])
        out.sell30.append(m1.sell30[e - 1])
    return out


class RollingStd:
    def __init__(self, n: int) -> None:
        self.q: deque[float] = deque(maxlen=n)
        self.s = self.ss = 0.0

    def std(self) -> float:
        k = len(self.q)
        if k < 50:
            return NAN
        var = (self.ss - self.s * self.s / k) / (k - 1)
        return math.sqrt(var) if var > 0 else NAN

    def mean(self) -> float:
        return self.s / len(self.q) if len(self.q) >= 50 else NAN

    def push(self, x: float) -> None:
        if len(self.q) == self.q.maxlen:
            old = self.q[0]
            self.s -= old
            self.ss -= old * old
        self.q.append(x)
        self.s += x
        self.ss += x * x


def _imb(b: float, s: float) -> float:
    t = b + s
    return (b - s) / t if t > 0 else 0.0


@dataclass
class Frame:
    """Per-candle features and context (NaN where undefined)."""

    feats: dict[str, list[float]]
    ret: list[float]
    atr: list[float]
    state: list[str]
    ema20: list[float]
    hi20: list[float]
    lo20: list[float]
    loc: list[float]


def frame(cd: Candles, btc_a3: dict[int, float] | None) -> Frame:
    n = len(cd.c)
    feats = {k: [NAN] * n for k in FEATURES}
    ret = [NAN] * n
    atr_l, ema_l, hi_l, lo_l, loc_l = [NAN] * n, [NAN] * n, [NAN] * n, [NAN] * n, [NAN] * n
    state_l = ["TRANSITION"] * n
    e20, e50, e200, atr_i, atr_pct = Ema(20), Ema(50), Ema(200), Atr(14), RollingPercentile(300)
    tracker = StateTracker()
    net_sd, ret_sd, n_mean = RollingStd(WIN), RollingStd(WIN), RollingStd(WIN)
    highs: deque[float] = deque(maxlen=20)
    lows: deque[float] = deque(maxlen=20)
    prev_c = NAN
    prev_e50 = NAN
    for j in range(n):
        c, h, lo = cd.c[j], cd.h[j], cd.lo[j]
        if c != c:  # missing day: restart every rolling state
            e20, e50, e200, atr_i, atr_pct = (
                Ema(20),
                Ema(50),
                Ema(200),
                Atr(14),
                RollingPercentile(300),
            )
            tracker = StateTracker()
            net_sd, ret_sd, n_mean = RollingStd(WIN), RollingStd(WIN), RollingStd(WIN)
            highs.clear()
            lows.clear()
            prev_c = prev_e50 = NAN
            continue
        r = math.log(c / prev_c) if prev_c == prev_c and prev_c > 0 else 0.0
        ret[j] = r
        net = cd.buy[j] - cd.sell[j]
        tot = cd.buy[j] + cd.sell[j]
        sd_net, sd_ret, mean_n = net_sd.std(), ret_sd.std(), n_mean.mean()
        a3 = net / sd_net if sd_net == sd_net else NAN
        f = feats
        f["A1"][j] = _imb(cd.buy[j], cd.sell[j])
        if j >= 2:
            f["A2"][j] = _imb(sum(cd.buy[j - 2 : j + 1]), sum(cd.sell[j - 2 : j + 1]))
        f["A3"][j] = a3
        f["A4"][j] = (cd.bb[j] - cd.bs[j]) / tot if tot > 0 else 0.0
        if sd_ret == sd_ret and a3 == a3:
            f["A5"][j] = a3 - r / sd_ret
        f["A6"][j] = _imb(cd.buy30[j], cd.sell30[j]) - f["A1"][j]
        if mean_n == mean_n and mean_n > 0:
            f["A7"][j] = cd.n[j] / mean_n * (1 if r > 0 else -1 if r < 0 else 0)
        if btc_a3 is not None:
            f["A8"][j] = btc_a3.get(cd.k_end[j], NAN)
        net_sd.push(net)
        ret_sd.push(r)
        n_mean.push(float(cd.n[j]))

        a = atr_i.update(h, lo, c)
        ap = atr_pct.update(a)
        x20, x50, x200 = e20.update(c), e50.update(c), e200.update(c)
        slope = x50 - prev_e50 if prev_e50 == prev_e50 else 0.0
        state_l[j] = tracker.update(h, lo, c, a, ap, (x20, x50, x200), slope, 0)
        atr_l[j], ema_l[j], loc_l[j] = a, x20, tracker.location_in_range(c)
        if len(highs) == 20:
            hi_l[j], lo_l[j] = max(highs), min(lows)
        highs.append(h)
        lows.append(lo)
        prev_c, prev_e50 = c, x50
    return Frame(feats, ret, atr_l, state_l, ema_l, hi_l, lo_l, loc_l)


def setups(cd: Candles, fr: Frame, j: int) -> list[tuple[str, int]]:
    a, c, h, lo, o = fr.atr[j], cd.c[j], cd.h[j], cd.lo[j], cd.o[j]
    a3, a4, a7 = fr.feats["A3"][j], fr.feats["A4"][j], fr.feats["A7"][j]
    if not (a == a and a > 0 and a3 == a3):
        return []
    st, e20, hi20, lo20 = fr.state[j], fr.ema20[j], fr.hi20[j], fr.lo20[j]
    out = []
    for d in (1, -1):
        trend = "UPTREND" if d == 1 else "DOWNTREND"
        touch = lo if d == 1 else h
        if st == trend and abs(touch - e20) <= 0.3 * a and d * a3 >= 1.5:
            out.append(("B-A", d))
        if hi20 == hi20:
            edge = hi20 if d == 1 else lo20
            if d * (c - edge) > 0.1 * a and d * a3 >= 2 and d * a4 > 0:
                out.append(("B-B", d))
            ext = lo20 if d == 1 else hi20
            swept = lo < ext if d == 1 else h > ext
            back = d * (c - ext) > 0
            half = d * (c - (h + lo) / 2) >= 0
            if swept and back and half and d * a3 <= -1.5:
                out.append(("B-C", d))
        loc = fr.loc[j]
        if st == "RANGE" and (loc <= 0.2 if d == 1 else loc >= 0.8) and d * a3 >= 1:
            out.append(("B-D", d))
        if d * (c - o) >= 1.5 * a and d * a3 >= 2 and a7 == a7 and d * a7 >= 2:
            out.append(("B-E", d))
    return out


# --- statistics -----------------------------------------------------------------------------
def _ranks(x: list[float]) -> list[float]:
    order = sorted(range(len(x)), key=x.__getitem__)
    r = [0.0] * len(x)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
            j += 1
        avg = (i + j) / 2
        for t in range(i, j + 1):
            r[order[t]] = avg
        i = j + 1
    return r


def spearman(x: list[float], y: list[float]) -> float:
    if len(x) < 10:
        return NAN
    rx, ry = _ranks(x), _ranks(y)
    n = len(x)
    mx, my = sum(rx) / n, sum(ry) / n
    sxy = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    sxx = sum((a - mx) ** 2 for a in rx)
    syy = sum((b - my) ** 2 for b in ry)
    return sxy / math.sqrt(sxx * syy) if sxx > 0 and syy > 0 else NAN


def tstat(xs: list[float]) -> tuple[float, float, int]:
    xs = [x for x in xs if x == x]
    k = len(xs)
    if k < 3:
        return NAN, NAN, k
    m = sum(xs) / k
    sd = math.sqrt(sum((x - m) ** 2 for x in xs) / (k - 1))
    return m, (m / sd * math.sqrt(k) if sd > 0 else NAN), k


def fwd(b: Buckets, k_end: int, lat_s: int, h_min: int) -> float:
    p0, p1 = b.px_at(k_end, lat_s), b.px_at(k_end, lat_s + 60 * h_min)
    return math.log(p1 / p0) if p0 == p0 and p1 == p1 and p0 > 0 else NAN


def day_key(b: Buckets, k: int) -> int:
    return (b.start_ms + k * BUCKET_MS) // 86_400_000


# --- run ------------------------------------------------------------------------------------
def run(segment: str, tfs: list[str]) -> dict[str, Any]:
    first, last = SEGMENTS[segment]
    t0 = time.time()
    # ic[(tf, feat, H)] -> list of (symbol, day, ic)
    ic: dict[tuple[str, str, int], list[tuple[str, int, float]]] = defaultdict(list)
    # ev[(tf, setup, H)] -> list of (symbol, d, ms, {lat: bp})
    ev: dict[tuple[str, str, int], list[tuple[str, int, int, dict[int, float]]]] = defaultdict(list)
    quality: dict[str, Any] = {}
    btc_a3: dict[str, dict[int, float]] = {}
    for sym in SYMBOLS:  # BTC first: its A3 feeds A8 for the alts
        b = load(sym, first, last)
        quality[sym] = {"buckets": len(b), "missing_days": b.missing_days}
        m1 = minute_candles(b)
        for tf in tfs:
            cd = aggregate(m1, TF_BUCKETS[tf] // 12)
            fr = frame(cd, None if sym == LEADER else btc_a3.get(tf))
            if sym == LEADER:
                btc_a3[tf] = {k: v for k, v in zip(cd.k_end, fr.feats["A3"], strict=True) if v == v}
            tf_min = TF_BUCKETS[tf] * BUCKET_MS // 60_000
            n = len(cd.c)
            for hm in HORIZONS_MIN:
                step = max(1, hm // tf_min)
                fwd_r = [
                    fwd(b, cd.k_end[j], LATENCY_S, hm) if j % step == 0 else NAN for j in range(n)
                ]
                for feat in FEATURES:
                    if feat == "A8" and sym == LEADER:
                        continue
                    xs = fr.feats[feat]
                    per_day: dict[int, tuple[list[float], list[float]]] = defaultdict(
                        lambda: ([], [])
                    )
                    for j in range(WARMUP, n, step):
                        x, y = xs[j], fwd_r[j]
                        if x == x and y == y:
                            px, py = per_day[day_key(b, cd.k_end[j])]
                            px.append(x)
                            py.append(y)
                    for dk, (px, py) in per_day.items():
                        v = spearman(px, py)
                        if v == v:
                            ic[(tf, feat, hm)].append((sym, dk, v))
            last_ev: dict[tuple[str, int, int], int] = {}
            for j in range(WARMUP, n):
                for name, d in setups(cd, fr, j):
                    ms = b.start_ms + cd.k_end[j] * BUCKET_MS
                    for hm in HORIZONS_MIN:
                        key = (name, d, hm)
                        if ms - last_ev.get(key, -(10**15)) < hm * 60_000:
                            continue
                        lats = {lat: fwd(b, cd.k_end[j], lat, hm) for lat in LATENCIES_S}
                        if lats[LATENCY_S] != lats[LATENCY_S]:
                            continue
                        last_ev[key] = ms
                        bp = {lat: d * v * 1e4 for lat, v in lats.items() if v == v}
                        ev[(tf, name, hm)].append((sym, d, ms, bp))
        print(f"  {sym} done ({time.time() - t0:.0f}s, missing days {b.missing_days})", flush=True)
    return summarise(segment, ic, ev, quality)


def summarise(
    segment: str,
    ic: dict[tuple[str, str, int], list[tuple[str, int, float]]],
    ev: dict[tuple[str, str, int], list[tuple[str, int, int, dict[int, float]]]],
    quality: dict[str, Any],
) -> dict[str, Any]:
    half_day = HALF_SPLIT_MS // 86_400_000
    stage_a = []
    for (tf, feat, hm), rows in sorted(ic.items()):
        mean, t, k = tstat([v for _, _, v in rows])
        per_sym = {s: tstat([v for s2, _, v in rows if s2 == s])[0] for s in SYMBOLS}
        signs = [v for v in per_sym.values() if v == v]
        same = sum(1 for v in signs if mean == mean and v * mean > 0)
        h1 = tstat([v for _, dk, v in rows if dk < half_day])[0]
        h2 = tstat([v for _, dk, v in rows if dk >= half_day])[0]
        ok = (
            t == t and abs(t) >= 3 and same >= 9 and h1 == h1 and h2 == h2 and h1 * mean > 0
            and h2 * mean > 0
        )  # fmt: skip
        stage_a.append({"tf": tf, "feature": feat, "h_min": hm, "mean_ic": round(mean, 4),
                        "t": round(t, 2), "symbol_days": k, "same_sign_symbols": same,
                        "half1": round(h1, 4), "half2": round(h2, 4), "pass": ok})  # fmt: skip
    stage_b = []
    for (tf, name, hm), evs in sorted(ev.items()):
        main = [r[3][LATENCY_S] for r in evs]
        avg = sum(main) / len(main) if main else NAN
        decay = {}
        for lat in LATENCIES_S:
            vals = [r[3][lat] for r in evs if lat in r[3]]
            decay[lat] = round(sum(vals) / len(vals), 2) if vals else None
        sym_stats = {}
        for s in SYMBOLS:
            vals = [r[3][LATENCY_S] for r in evs if r[0] == s]
            if vals:
                sym_stats[s] = (len(vals), round(sum(vals) / len(vals), 2))
        pos = sum(1 for _, sm in sym_stats.values() if sm > 0)
        first = [r[3][LATENCY_S] for r in evs if r[2] < HALF_SPLIT_MS]
        second = [r[3][LATENCY_S] for r in evs if r[2] >= HALF_SPLIT_MS]
        m1 = sum(first) / len(first) if first else NAN
        m2 = sum(second) / len(second) if second else NAN
        lng = [r[3][LATENCY_S] for r in evs if r[1] == 1]
        sht = [r[3][LATENCY_S] for r in evs if r[1] == -1]
        _, tb, _ = tstat(main)
        ok = avg >= 9 and pos >= 9 and m1 > 0 and m2 > 0 and len(main) >= 300
        stage_b.append({"tf": tf, "setup": name, "h_min": hm, "n": len(main),
                        "mean_bp": round(avg, 2), "t": round(tb, 2), "decay_bp": decay,
                        "half1": round(m1, 2), "half2": round(m2, 2), "symbols_positive": pos,
                        "long_bp": round(sum(lng) / len(lng), 2) if lng else None,
                        "short_bp": round(sum(sht) / len(sht), 2) if sht else None,
                        "per_symbol": sym_stats, "pass": ok})  # fmt: skip
    return {"segment": segment, "latency_s": LATENCY_S, "quality": quality,
            "stage_a": stage_a, "stage_b": stage_b}  # fmt: skip


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["run"])
    p.add_argument("--segment", default="dev", choices=sorted(SEGMENTS))
    p.add_argument("--tfs", default="1m,5m,10m")
    a = p.parse_args()
    res = run(a.segment, a.tfs.split(","))
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"stage_ab_{a.segment}.json"
    path.write_text(json.dumps(res, indent=1, default=str))
    print("Stage A passes:")
    for r in res["stage_a"]:
        if r["pass"]:
            print("  ", r)
    print("Stage A strongest |t| per tf:")
    for tf in a.tfs.split(","):
        rows = sorted((r for r in res["stage_a"] if r["tf"] == tf), key=lambda r: -abs(r["t"] or 0))
        for r in rows[:8]:
            print(f"   {tf} {r['feature']} H{r['h_min']} ic={r['mean_ic']} t={r['t']} "
                  f"same={r['same_sign_symbols']} h1={r['half1']} h2={r['half2']} "
                  f"pass={r['pass']}")  # fmt: skip
    print("Stage B:")
    for r in res["stage_b"]:
        print(f"   {r['tf']} {r['setup']} H{r['h_min']} n={r['n']} mean={r['mean_bp']}bp "
              f"t={r['t']} "
              f"decay={r['decay_bp']} h1={r['half1']} h2={r['half2']} pos={r['symbols_positive']} "
              f"L={r['long_bp']} S={r['short_bp']} pass={r['pass']}")  # fmt: skip
    print("written", path)


if __name__ == "__main__":
    main()
