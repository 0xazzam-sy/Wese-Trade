"""Phase 8 order-book archive reducer: OKX L2 400-level daily files -> 5-second book features.

Source (docs/research-microscalp.md §1): archive module 4, one tar.gz per instrument per UTC day,
JSON lines `{"action": "snapshot"|"update", "ts", "asks": [[px, sz, n], ...], "bids": [...]}`.
Size 0 deletes a level. Each snapshot resets the book. Nothing is reconstructed from candles.

Per 5 s bucket (state at the bucket's end boundary; NaN while the book is empty or crossed):
    mid, spread_bp, imb1 (top-of-book size imbalance), imb5 (top 5 levels),
    dimb10 / dimb25 (notional
    depth imbalance within 10 / 25 bp of mid), micro_bp (microprice - mid), depth25 (bid + ask
    notional within 25 bp, contract units x price)

    python -m app.research.micro.book ingest --symbols ETHUSDT,SOLUSDT --since 2026-06-10 \
        --until 2026-08-01 [--every 1] [--workers 2]
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
import tempfile
from array import array
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.research.micro.trades import BUCKET_MS, PER_DAY, inst_id
from app.research.store import RESEARCH_DIR

ROOT = RESEARCH_DIR / "micro" / "book5s"
URL = (
    "https://www.okx.com/cdn/okx/match/orderbook/pro/L2/400lv/daily/{d}/"
    "{inst}-L2orderbook-400lv-{iso}.tar.gz"
)
FIELDS = ("mid", "spread_bp", "imb1", "imb5", "dimb10", "dimb25", "micro_bp", "depth25")
NAN = math.nan
# Order-book splits (docs §3): the archive window starts 2026-06-10.
BOOK_DEV = (date(2026, 6, 10), date(2026, 7, 31))
BOOK_VAL = (date(2026, 8, 1), date(2026, 8, 31))
BOOK_HOLDOUT_START = date(2026, 9, 1)


class BookHoldoutLockedError(RuntimeError):
    pass


def utc_midnight_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)


def day_path(symbol: str, day: date) -> Path:
    return ROOT / symbol / f"{day:%Y%m%d}.bin"


def _features(bids: dict[float, float], asks: dict[float, float]) -> tuple[float, ...] | None:
    if not bids or not asks:
        return None
    bb, ba = max(bids), min(asks)
    if bb >= ba:
        return None
    mid = (bb + ba) / 2
    bs1, as1 = bids[bb], asks[ba]
    top_b = sorted(bids, reverse=True)[:5]
    top_a = sorted(asks)[:5]
    b5 = sum(bids[p] for p in top_b)
    a5 = sum(asks[p] for p in top_a)
    lo10, hi10 = mid * (1 - 1e-3), mid * (1 + 1e-3)
    lo25, hi25 = mid * (1 - 2.5e-3), mid * (1 + 2.5e-3)
    bd10 = bd25 = ad10 = ad25 = 0.0
    for p, s in bids.items():
        if p >= lo25:
            v = p * s
            bd25 += v
            if p >= lo10:
                bd10 += v
    for p, s in asks.items():
        if p <= hi25:
            v = p * s
            ad25 += v
            if p <= hi10:
                ad10 += v
    micro = (bb * as1 + ba * bs1) / (bs1 + as1) if bs1 + as1 > 0 else mid

    def imb(x: float, y: float) -> float:
        return (x - y) / (x + y) if x + y > 0 else 0.0

    return (
        mid,
        (ba - bb) / mid * 1e4,
        imb(bs1, as1),
        imb(b5, a5),
        imb(bd10, ad10),
        imb(bd25, ad25),
        (micro - mid) / mid * 1e4,
        bd25 + ad25,
    )


def reduce_stream(lines: Any, day_ms: int) -> dict[str, Any]:
    out = {k: array("d", [NAN]) * PER_DAY for k in FIELDS}
    q: dict[str, Any] = {"lines": 0, "snapshots": 0, "updates": 0, "crossed": 0,
                         "out_of_order": 0, "bad": 0, "outside_day": 0}  # fmt: skip
    bids: dict[float, float] = {}
    asks: dict[float, float] = {}
    k_next = 0  # next bucket boundary to emit (index of the bucket that ends there)
    last_ts = -1

    def emit_until(ts: int) -> None:
        nonlocal k_next
        # all boundaries strictly before or at ts get the state as it was before this message
        while k_next < PER_DAY and day_ms + (k_next + 1) * BUCKET_MS <= ts:
            f = _features(bids, asks)
            if f is None:
                if bids and asks:
                    q["crossed"] += 1
            else:
                for name, v in zip(FIELDS, f, strict=True):
                    out[name][k_next] = v
            k_next += 1

    for raw in lines:
        q["lines"] += 1
        try:
            m = json.loads(raw)
            ts = int(m["ts"])
        except (ValueError, KeyError, TypeError):
            q["bad"] += 1
            continue
        if ts < last_ts:
            q["out_of_order"] += 1
        last_ts = max(last_ts, ts)
        if ts < day_ms or ts >= day_ms + 86_400_000:
            q["outside_day"] += 1
        emit_until(ts)
        if m.get("action") == "snapshot":
            q["snapshots"] += 1
            bids.clear()
            asks.clear()
        else:
            q["updates"] += 1
        for side, book in (("bids", bids), ("asks", asks)):
            for lvl in m.get(side) or ():
                p, s = float(lvl[0]), float(lvl[1])
                if s == 0:
                    book.pop(p, None)
                else:
                    book[p] = s
    emit_until(day_ms + 86_400_000)
    q["first_bucket_ms"] = day_ms
    q["filled_buckets"] = sum(1 for x in out["spread_bp"] if x == x)
    return {"arrays": out, "quality": q}


def write_day(symbol: str, day: date, reduced: dict[str, Any]) -> None:
    path = day_path(symbol, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as f:
        for name in FIELDS:
            reduced["arrays"][name].tofile(f)
    tmp.replace(path)
    path.with_suffix(".json").write_text(json.dumps(reduced["quality"]))


def read_day(symbol: str, day: date, *, unlock_holdout: bool = False) -> dict[str, Any] | None:
    if day >= BOOK_HOLDOUT_START and not unlock_holdout:
        raise BookHoldoutLockedError("order-book holdout days are locked")
    path = day_path(symbol, day)
    if not path.exists():
        return None
    out: dict[str, Any] = {}
    with path.open("rb") as f:
        for name in FIELDS:
            a: array[float] = array("d")
            a.fromfile(f, PER_DAY)
            out[name] = a
    return out


def ingest_day(args: tuple[str, str]) -> tuple[str, str, str]:
    symbol, iso = args
    d = date.fromisoformat(iso)
    if day_path(symbol, d).exists():
        return symbol, iso, "exists"
    url = URL.format(d=f"{d:%Y%m%d}", inst=inst_id(symbol), iso=iso)
    with tempfile.TemporaryDirectory() as tmpdir:
        gz = Path(tmpdir) / "b.tar.gz"
        curl = shutil.which("curl") or "curl"
        cmd = [curl, "-sf", "--retry", "4", "--retry-delay", "5", "-m", "1800", "-o", str(gz), url]
        if subprocess.run(cmd, check=False).returncode != 0:  # noqa: S603
            return symbol, iso, "missing"
        tar = shutil.which("tar") or "tar"
        with subprocess.Popen(  # noqa: S603
            [tar, "xzOf", str(gz)], stdout=subprocess.PIPE, text=True, bufsize=1 << 20
        ) as proc:
            if proc.stdout is None:
                raise RuntimeError("tar produced no output stream")
            reduced = reduce_stream(proc.stdout, utc_midnight_ms(d))
    write_day(symbol, d, reduced)
    q = reduced["quality"]
    return symbol, iso, f"lines={q['lines']} filled={q['filled_buckets']} crossed={q['crossed']}"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("command", choices=["ingest"])
    p.add_argument("--symbols", required=True)
    p.add_argument("--since", required=True)
    p.add_argument("--until", required=True)
    p.add_argument("--every", type=int, default=1)
    p.add_argument("--workers", type=int, default=2)
    a = p.parse_args()
    d, end = date.fromisoformat(a.since), date.fromisoformat(a.until)
    days = []
    while d < end:
        days.append(d.isoformat())
        d += timedelta(days=a.every)
    jobs = [(s, iso) for iso in days for s in a.symbols.split(",")]
    with ProcessPoolExecutor(a.workers) as pool:
        for res in pool.map(ingest_day, jobs):
            print(*res, flush=True)


if __name__ == "__main__":
    main()
