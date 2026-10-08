"""OKX trade-archive ingestion -> causal 5-second trade-flow buckets.

Source: OKX public historical-data archive, module 1 (daily CSV of every trade with the
aggressor `side`). Nothing is inferred from candles. Each day is reduced to 17,280 buckets:

    last, high, low (float64)  buy_vol, sell_vol (float32, size x price)
    buy_n, sell_n (int32)      big_buy, big_sell (float32: trades >= previous day's p99 size)

    python -m app.research.micro.trades ingest --since 2025-10-07 --until 2026-10-07
"""

from __future__ import annotations

import argparse
import io
import json
import math
import shutil
import subprocess
import tempfile
import zipfile
from array import array
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from app.research.ltf5.data import HOLDOUT_START_MS, HoldoutLockedError
from app.research.ltf5.run import members
from app.research.store import RESEARCH_DIR

ROOT = RESEARCH_DIR / "micro" / "trades5s"
BUCKET_MS = 5_000
# Archive files follow UTC+8 calendar days: file D covers [D 00:00 UTC+8, D+1 00:00 UTC+8),
# i.e. [D-1 16:00 UTC, D 16:00 UTC). Buckets start at that instant.
DAY_OFFSET_MS = -8 * 3_600_000
PER_DAY = 86_400_000 // BUCKET_MS
URL = "https://www.okx.com/cdn/okex/traderecords/trades/daily/{d}/{inst}-trades-{iso}.zip"
FIELDS = (
    ("last", "d"), ("high", "d"), ("low", "d"), ("buy_vol", "f"), ("sell_vol", "f"),
    ("buy_n", "i"), ("sell_n", "i"), ("big_buy", "f"), ("big_sell", "f"),
)  # fmt: skip


def inst_id(symbol: str) -> str:
    return symbol.replace("USDT", "-USDT-SWAP")


def day_start_ms(day: date) -> int:
    """First instant (UTC ms) covered by the archive file of `day`."""
    return (
        int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000) + DAY_OFFSET_MS
    )


def day_path(symbol: str, day: date) -> Path:
    return ROOT / symbol / f"{day:%Y%m%d}.bin"


def reduce_day(
    csv_lines: io.TextIOBase, day_ms: int, big_threshold: float | None
) -> dict[str, Any]:
    nan = math.nan
    out: dict[str, Any] = {
        "last": array("d", [nan]) * PER_DAY, "high": array("d", [nan]) * PER_DAY,
        "low": array("d", [nan]) * PER_DAY, "buy_vol": array("f", [0.0]) * PER_DAY,
        "sell_vol": array("f", [0.0]) * PER_DAY, "buy_n": array("i", [0]) * PER_DAY,
        "sell_n": array("i", [0]) * PER_DAY, "big_buy": array("f", [0.0]) * PER_DAY,
        "big_sell": array("f", [0.0]) * PER_DAY,
    }  # fmt: skip
    q: dict[str, Any] = {
        "trades": 0,
        "duplicates": 0,
        "out_of_order": 0,
        "outside_day": 0,
        "bad_rows": 0,
    }
    sizes: list[float] = []
    last_id = -1
    last_ts = -1
    first_ts = None
    header = csv_lines.readline()
    if not header.startswith("instrument_name"):
        raise ValueError(f"unexpected trade archive header: {header[:60]!r}")
    last, high, low = out["last"], out["high"], out["low"]
    bv, sv, bn, sn = out["buy_vol"], out["sell_vol"], out["buy_n"], out["sell_n"]
    bb, sb = out["big_buy"], out["big_sell"]
    for line in csv_lines:
        parts = line.rstrip("\r\n").split(",")
        if len(parts) < 6:
            q["bad_rows"] += 1
            continue
        try:
            tid = int(parts[1])
            side = parts[2]
            px = float(parts[3])
            sz = float(parts[4])
            ts = int(parts[5])
        except ValueError:
            q["bad_rows"] += 1
            continue
        if tid <= last_id:
            q["duplicates"] += 1
            continue
        last_id = tid
        if ts < last_ts:
            q["out_of_order"] += 1
        last_ts = max(last_ts, ts)
        k = (ts - day_ms) // BUCKET_MS
        if not 0 <= k < PER_DAY or px <= 0 or sz <= 0 or side not in ("buy", "sell"):
            q["outside_day" if not 0 <= k < PER_DAY else "bad_rows"] += 1
            continue
        q["trades"] += 1
        first_ts = ts if first_ts is None else first_ts
        sizes.append(sz)
        notional = sz * px
        last[k] = px
        if not (high[k] >= px):
            high[k] = px
        if not (low[k] <= px):
            low[k] = px
        big = big_threshold is not None and sz >= big_threshold
        if side == "buy":
            bv[k] += notional
            bn[k] += 1
            if big:
                bb[k] += notional
        else:
            sv[k] += notional
            sn[k] += 1
            if big:
                sb[k] += notional
    sizes.sort()
    q["p99_size"] = sizes[int(0.99 * (len(sizes) - 1))] if sizes else None
    q["first_ts"], q["last_ts"] = first_ts, last_ts
    q["big_threshold"] = big_threshold
    q["day_start_ms"] = day_ms
    return {"arrays": out, "quality": q}


def write_day(symbol: str, day: date, reduced: dict[str, Any]) -> None:
    path = day_path(symbol, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as f:
        for name, _ in FIELDS:
            reduced["arrays"][name].tofile(f)
    tmp.replace(path)
    path.with_suffix(".json").write_text(json.dumps(reduced["quality"]))


def read_day(symbol: str, day: date, *, unlock_holdout: bool = False) -> dict[str, Any] | None:
    if day_start_ms(day) + 86_400_000 > HOLDOUT_START_MS and not unlock_holdout:
        raise HoldoutLockedError("trade-flow holdout days are locked until a candidate is frozen")
    path = day_path(symbol, day)
    if not path.exists():
        return None
    out: dict[str, Any] = {}
    with path.open("rb") as f:
        for name, code in FIELDS:
            a: array[Any] = array(code)
            a.fromfile(f, PER_DAY)
            out[name] = a
    return out


def ingest_symbol(args: tuple[str, str, str]) -> tuple[str, int, int]:
    symbol, since, until = args
    d, end = date.fromisoformat(since), date.fromisoformat(until)
    threshold: float | None = None
    done = missing = 0
    while d < end:
        path = day_path(symbol, d)
        meta = path.with_suffix(".json")
        if path.exists() and meta.exists():
            threshold = json.loads(meta.read_text()).get("p99_size")
            d += timedelta(days=1)
            done += 1
            continue
        url = URL.format(d=f"{d:%Y%m%d}", inst=inst_id(symbol), iso=d.isoformat())
        with tempfile.TemporaryDirectory() as tmpdir:
            zpath = Path(tmpdir) / "t.zip"
            curl = shutil.which("curl") or "curl"
            cmd = [curl, "-sf", "--retry", "4", "--retry-delay", "3", "-m", "300"]
            r = subprocess.run([*cmd, "-o", str(zpath), url], check=False)  # noqa: S603
            if r.returncode != 0 or not zpath.exists():
                missing += 1
                ROOT.joinpath(symbol).mkdir(parents=True, exist_ok=True)
                ROOT.joinpath(symbol, f"{d:%Y%m%d}.missing").write_text(url)
                threshold = None  # the next day cannot use a causal threshold
                d += timedelta(days=1)
                continue
            day_ms = day_start_ms(d)
            with zipfile.ZipFile(zpath) as z, z.open(z.namelist()[0]) as raw:
                text = io.TextIOWrapper(raw, encoding="utf-8", errors="replace")
                reduced = reduce_day(text, day_ms, threshold)
        write_day(symbol, d, reduced)
        threshold = reduced["quality"]["p99_size"]
        done += 1
        d += timedelta(days=1)
    return symbol, done, missing


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["ingest"])
    p.add_argument("--since", default="2025-10-06")
    p.add_argument("--until", default="2026-10-08")
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args()
    jobs = [(s, a.since, a.until) for s, _ in members()]
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for symbol, done, missing in pool.map(ingest_symbol, jobs):
            print(f"{symbol}: {done} days, {missing} missing", flush=True)


if __name__ == "__main__":
    main()
