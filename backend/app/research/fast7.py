"""Phase 7 Stage 1: plan-independent market-behaviour screen (docs/research-fast7.md §2).

For every causal module event (closed candles only) the signed forward return from the trigger
close to the close h candles later is measured in basis points, with 30-candle MFE / MAE.
Development data only (the holdout is locked by the loader).

    python -m app.research.fast7 screen --tf 5m
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from typing import Any

from app.fast7.state import StateTracker
from app.research.ltf5 import data
from app.research.ltf5.data import DEV_END_MS, Series
from app.research.ltf5.run import OUT, members
from app.scalp6.engine import Profile, Scalp6Engine

HORIZONS = (5, 15, 30, 60)
EXCURSION = 30
COOLDOWN = 5
HURDLE_TAKER_BP = 14.0
HURDLE_MAKER_BP = 6.0
SCREEN_BP = 1.5 * HURDLE_MAKER_BP
SESSIONS_UTC = ((7, 0), (13, 30))
MODULES = ("M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7")


def series_for(symbol: str, tf: str) -> Series:
    if tf == "1m":
        return data.load(symbol, "1m")[0]
    base5 = data.load(symbol, "5m")[0]
    return base5 if tf == "5m" else data.aggregate(base5, tf)


def events(s: Series, tf: str) -> list[tuple[str, int, int]]:
    """(module, side, candle index) for every causal module event."""
    eng = Scalp6Engine(Profile(tf, fractal=3 if tf == "1m" else 2), s.step)
    st = StateTracker()
    out: list[tuple[str, int, int]] = []
    last: dict[tuple[str, int], int] = {}
    breakouts: list[tuple[float, int, int]] = []  # (level, candle, side)
    orb: dict[
        int, list[float]
    ] = {}  # session start ms -> [hi, lo, end_ms, fired_long, fired_short]
    step = s.step
    for i in range(len(s)):
        o, h, lo, c, v = s.o[i], s.h[i], s.lo[i], s.c[i], s.v[i]
        eng.update(s.t[i], o, h, lo, c, v, [])
        atr = eng.atr.value or 0.0
        ef, em, es = eng.ema_f.value or c, eng.ema_m.value or c, eng.ema_s.value or c
        state = st.update(
            h, lo, c, atr, eng.pct, (ef, em, es), eng.ema_m.slope(), eng.structure.direction
        )
        if eng.warm < 200 or not atr:
            continue
        rng = h - lo

        def emit(mod: str, side: int, _i: int = i) -> None:
            if _i - last.get((mod, side), -999) >= COOLDOWN:
                out.append((mod, side, _i))
                last[(mod, side)] = _i

        # M0 baseline: time-series momentum every 20 candles
        if i % 20 == 0 and i >= 20:
            r20 = c - s.c[i - 20]
            if r20:
                emit("M0", 1 if r20 > 0 else -1)
        sup = eng.levels.nearest(c, above=False, i=eng.i, min_grade="medium")
        res = eng.levels.nearest(c, above=True, i=eng.i, min_grade="medium")
        # M1 trend pullback + micro-BOS
        if state in ("UPTREND", "DOWNTREND") and i >= 6:
            side = 1 if state == "UPTREND" else -1
            if side == 1:
                pulled = min(s.lo[i - 5 : i + 1]) <= em + 0.2 * atr or (
                    sup and c - sup[0].price <= 1.0 * atr
                )
                trig = c > max(s.h[i - 3 : i]) and s.c[i - 1] <= max(s.h[i - 4 : i - 1])
                room = not res or res[0].price - c > 1.0 * atr
            else:
                pulled = max(s.h[i - 5 : i + 1]) >= em - 0.2 * atr or (
                    res and res[0].price - c <= 1.0 * atr
                )
                trig = c < min(s.lo[i - 3 : i]) and s.c[i - 1] >= min(s.lo[i - 4 : i - 1])
                room = not sup or c - sup[0].price > 1.0 * atr
            if pulled and trig and room:
                emit("M1", side)
        # M2 breakout + retest: remember decisive breaks of medium+ levels
        prev_c = s.c[i - 1] if i else c
        for lv in eng.levels.levels:
            if lv.grade(eng.i) == "weak":
                continue
            if prev_c <= lv.price < c - 0.3 * atr:
                breakouts.append((lv.price, i, 1))
            elif prev_c >= lv.price > c + 0.3 * atr:
                breakouts.append((lv.price, i, -1))
        keep = []
        for p, bi, side in breakouts:
            if i - bi > 20:
                continue
            if i > bi and (
                (side == 1 and lo <= p + 0.3 * atr and c > p and c > o)
                or (side == -1 and h >= p - 0.3 * atr and c < p and c < o)
            ):
                emit("M2", side)
                continue  # consumed
            keep.append((p, bi, side))
        breakouts = keep[-20:]
        # M3 momentum expansion after compression
        if st.was("COMPRESSION", 10) and rng >= 1.5 * atr and eng.rel_vol >= 1.5 and rng > 0:
            loc = (c - lo) / rng
            if loc >= 0.8:
                emit("M3", 1)
            elif loc <= 0.2:
                emit("M3", -1)
        # M4 liquidity sweep reversal at a level / range edge
        sw = eng.structure.last_sweep
        if sw is not None and sw[0] == eng.i and state in ("RANGE", "TRANSITION"):
            side = sw[1]
            pos = st.location_in_range(c)
            near = sup if side == 1 else res
            at_level = bool(near) and abs(near[0].price - sw[2]) <= 0.3 * atr
            edge = pos <= 0.2 if side == 1 else pos >= 0.8
            if (at_level or edge) and side * (c - o) > 0:
                emit("M4", side)
        # M5 range edge reversal
        if state == "RANGE" and rng > 0:
            pos = st.location_in_range(c)
            lower_wick, upper_wick = min(o, c) - lo, h - max(o, c)
            if pos <= 0.2 and sup and c - sup[0].price <= 0.5 * atr and lower_wick >= 0.5 * rng:
                emit("M5", 1)
            if pos >= 0.8 and res and res[0].price - c <= 0.5 * atr and upper_wick >= 0.5 * rng:
                emit("M5", -1)
        # M6 extension mean reversion
        if state != "EXPANSION":
            z = (c - em) / atr
            if z <= -3 and c > o and c > prev_c:
                emit("M6", 1)
            elif z >= 3 and c < o and c < prev_c:
                emit("M6", -1)
        # M7 session opening range (30 minutes) breakout, first close beyond, within 4 h
        open_ms = s.t[i]
        day = open_ms - open_ms % 86_400_000
        for hh, mm in SESSIONS_UTC:
            start = day + (hh * 60 + mm) * 60_000
            end = start + 30 * 60_000
            if start <= open_ms and open_ms + step <= end:
                rec = orb.setdefault(start, [h, lo, end, 0.0, 0.0])
                rec[0], rec[1] = max(rec[0], h), min(rec[1], lo)
            elif start in orb and end <= open_ms < start + 4 * 3_600_000:
                rec = orb[start]
                if c > rec[0] and not rec[3]:
                    rec[3] = 1.0
                    emit("M7", 1)
                elif c < rec[1] and not rec[4]:
                    rec[4] = 1.0
                    emit("M7", -1)
        if len(orb) > 8:
            for k in sorted(orb)[:-4]:
                del orb[k]
    return out


def measure(symbol: str, tf: str) -> tuple[str, list[dict[str, Any]]]:
    s = series_for(symbol, tf)
    rows = []
    n = len(s)
    for mod, side, i in events(s, tf):
        if s.t[i] + s.step >= DEV_END_MS:
            continue
        c = s.c[i]
        fwd = {}
        for hz in HORIZONS:
            if i + hz < n:
                fwd[hz] = side * (s.c[i + hz] - c) / c * 1e4
        if len(fwd) < len(HORIZONS):
            continue
        hi = max(s.h[i + 1 : i + 1 + EXCURSION])
        low = min(s.lo[i + 1 : i + 1 + EXCURSION])
        mfe = (hi - c) / c * 1e4 if side == 1 else (c - low) / c * 1e4
        mae = (c - low) / c * 1e4 if side == 1 else (hi - c) / c * 1e4
        rows.append(
            {"m": mod, "side": side, "t": s.t[i], "fwd": fwd, "mfe": mfe, "mae": mae, "sym": symbol}
        )
    return symbol, rows


def _job(args: tuple[str, str]) -> tuple[str, list[dict[str, Any]]]:
    return measure(*args)


def screen(tf: str) -> dict[str, Any]:
    t0 = time.time()
    rows: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=4) as pool:
        for _sym, r in pool.map(_job, [(s, tf) for s, _ in members()]):
            rows += r
    times = sorted(r["t"] for r in rows)
    mid = times[len(times) // 2] if times else 0
    result: dict[str, Any] = {}
    for mod in MODULES:
        sub = [r for r in rows if r["m"] == mod]
        if not sub:
            result[mod] = {"n": 0}
            continue
        entry: dict[str, Any] = {"n": len(sub), "long": sum(r["side"] == 1 for r in sub)}
        best_h, best = None, -1e9
        for hz in HORIZONS:
            vals = [r["fwd"][hz] for r in sub]
            mean = statistics.fmean(vals)
            by_sym: dict[str, list[float]] = defaultdict(list)
            for r in sub:
                by_sym[r["sym"]].append(r["fwd"][hz])
            pos_sym = sum(1 for v in by_sym.values() if len(v) >= 30 and statistics.fmean(v) > 0)
            elig = sum(1 for v in by_sym.values() if len(v) >= 30)
            h1 = [r["fwd"][hz] for r in sub if r["t"] < mid]
            h2 = [r["fwd"][hz] for r in sub if r["t"] >= mid]
            m1 = statistics.fmean(h1) if h1 else 0.0
            m2 = statistics.fmean(h2) if h2 else 0.0
            se = statistics.pstdev(vals) / len(vals) ** 0.5 if len(vals) > 1 else 0.0
            passed = mean >= SCREEN_BP and pos_sym >= 9 and m1 > 0 and m2 > 0 and len(sub) >= 300
            entry[f"h{hz}"] = {
                "mean_bp": round(mean, 2), "se_bp": round(se, 2), "pos_symbols": f"{pos_sym}/{elig}",
                "half1": round(m1, 2), "half2": round(m2, 2), "pass": passed,
                "long_bp": round(statistics.fmean([r["fwd"][hz] for r in sub if r["side"] == 1] or [0]), 2),
                "short_bp": round(statistics.fmean([r["fwd"][hz] for r in sub if r["side"] == -1] or [0]), 2),
            }  # fmt: skip
            if mean > best:
                best_h, best = hz, mean
        entry["mfe_bp"] = round(statistics.fmean(r["mfe"] for r in sub), 1)
        entry["mae_bp"] = round(statistics.fmean(r["mae"] for r in sub), 1)
        entry["best_h"] = best_h
        entry["pass"] = any(entry[f"h{hz}"]["pass"] for hz in HORIZONS)
        result[mod] = entry
    out = {"tf": tf, "events": len(rows), "seconds": round(time.time() - t0, 1), "modules": result}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"fast7_{tf}_screen.json").write_text(json.dumps(out, indent=1))
    print(f"== fast7 screen {tf}: {len(rows)} events ({out['seconds']}s); hurdles taker "
          f"{HURDLE_TAKER_BP} bp, maker {HURDLE_MAKER_BP} bp, screen bar {SCREEN_BP} bp")  # fmt: skip
    for mod, e in result.items():
        if not e.get("n"):
            print(f"  {mod}: no events")
            continue
        cols = "  ".join(
            f"h{hz}={e[f'h{hz}']['mean_bp']:+6.2f}({e[f'h{hz}']['pos_symbols']})" for hz in HORIZONS
        )
        print(f"  {mod}: n={e['n']:6} long={e['long']:6} {cols} mfe={e['mfe_bp']} mae={e['mae_bp']} "
              f"PASS={e['pass']}")  # fmt: skip
    return out


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["screen"])
    p.add_argument("--tf", choices=["1m", "5m", "10m"], default="5m")
    a = p.parse_args()
    screen(a.tf)


if __name__ == "__main__":
    main()
