"""Phase 8 order-book Stage A (docs/research-microscalp.md §6).

Uses only the reduced L2 archive (`book.py`): features at the 5 s state of each candle close;
targets are mid-price log returns from the +20 s mid (manual latency) over 1 / 5 / 10 / 30 minutes.
No trade-archive file is read, so the trade-flow holdout stays sealed.

    python -m app.research.micro.stage_book run [--segment dev|val]
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.research.micro.book import BOOK_DEV, BOOK_VAL, read_day
from app.research.micro.stage_ab import OUT, spearman, tstat
from app.research.micro.trades import PER_DAY

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "PEPEUSDT")
FEATURES = {"O1": "imb1", "O2": "imb5", "O3": "dimb10", "O4": "dimb25", "O5": "micro_bp",
            "O6": "spread_bp"}  # fmt: skip
TF_BUCKETS = {"1m": 12, "5m": 60, "10m": 120}
HORIZONS_MIN = (1, 5, 10, 30)
LATENCY_S = 20
HALF_SPLIT = {"dev": date(2026, 7, 5), "val": date(2026, 8, 16)}
SEGMENTS = {"dev": BOOK_DEV, "val": BOOK_VAL}


def _days(segment: str) -> list[date]:
    first, last = SEGMENTS[segment]
    out, d = [], first
    while d <= last:
        out.append(d)
        d += timedelta(days=1)
    return out


def run(segment: str) -> dict[str, Any]:
    rows: dict[tuple[str, str, int, int], list[tuple[str, date, float]]] = defaultdict(list)
    used: dict[str, int] = {}
    for sym in SYMBOLS:
        used[sym] = 0
        for d in _days(segment):
            day = read_day(sym, d)
            if day is None:
                continue
            used[sym] += 1
            mid = day["mid"]
            for tf, m in TF_BUCKETS.items():
                tf_min = m // 12
                for hm in HORIZONS_MIN:
                    step = max(1, hm // tf_min) * m
                    for lat in (0, LATENCY_S):
                        off = lat // 5
                        xs: dict[str, list[float]] = {k: [] for k in FEATURES}
                        ys: list[float] = []
                        for k_end in range(m, PER_DAY, step):
                            i0 = k_end - 1 + off
                            i1 = i0 + hm * 12
                            if i1 >= PER_DAY:
                                break
                            p0, p1 = mid[i0], mid[i1]
                            feats = [day[f][k_end - 1] for f in FEATURES.values()]
                            if not (p0 == p0 and p1 == p1) or any(v != v for v in feats):
                                continue
                            ys.append(math.log(p1 / p0))
                            for key, v in zip(FEATURES, feats, strict=True):
                                xs[key].append(v)
                        for key in FEATURES:
                            ic = spearman(xs[key], ys)
                            if ic == ic:
                                rows[(tf, key, hm, lat)].append((sym, d, ic))
    split = HALF_SPLIT[segment]
    out = []
    for (tf, key, hm, lat), vals in sorted(rows.items()):
        mean, t, n = tstat([v for _, _, v in vals])
        per_sym = {s: tstat([v for s2, _, v in vals if s2 == s])[0] for s in SYMBOLS}
        same = sum(1 for v in per_sym.values() if v == v and mean == mean and v * mean > 0)
        h1 = tstat([v for _, d, v in vals if d < split])[0]
        h2 = tstat([v for _, d, v in vals if d >= split])[0]
        ok = bool(
            t == t and abs(t) >= 3 and same >= 5 and h1 * mean > 0 and h2 * mean > 0
            and key != "O6" and lat == LATENCY_S
        )  # fmt: skip
        out.append({"tf": tf, "feature": key, "h_min": hm, "latency_s": lat,
                    "mean_ic": round(mean, 4), "t": round(t, 2), "symbol_days": n,
                    "same_sign_symbols": same, "half1": round(h1, 4), "half2": round(h2, 4),
                    "per_symbol": {s: round(v, 4) for s, v in per_sym.items() if v == v},
                    "pass": ok})  # fmt: skip
    return {"segment": segment, "days_used": used,
            "run_at": datetime.now(UTC).isoformat(), "stage_a_book": out}  # fmt: skip


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["run"])
    p.add_argument("--segment", default="dev", choices=sorted(SEGMENTS))
    a = p.parse_args()
    res = run(a.segment)
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"stage_book_{a.segment}.json"
    path.write_text(json.dumps(res, indent=1, default=str))
    print("days used:", res["days_used"])
    for r in res["stage_a_book"]:
        if r["latency_s"] == LATENCY_S:
            print(f"  {r['tf']:3} {r['feature']} H{r['h_min']:<2} ic={r['mean_ic']:+.4f} "
                  f"t={r['t']:+.2f} same={r['same_sign_symbols']}/6 h1={r['half1']:+.4f} "
                  f"h2={r['half2']:+.4f} pass={r['pass']}")  # fmt: skip
    lat0 = {(r["tf"], r["feature"], r["h_min"]): r["mean_ic"] for r in res["stage_a_book"]
            if r["latency_s"] == 0}  # fmt: skip
    print("decay (IC at +0 s -> +20 s):")
    for r in res["stage_a_book"]:
        if r["latency_s"] == LATENCY_S and abs(r["t"]) >= 3:
            k = (r["tf"], r["feature"], r["h_min"])
            print(f"  {k}: {lat0.get(k)} -> {r['mean_ic']}")
    print("written", path)


if __name__ == "__main__":
    main()
