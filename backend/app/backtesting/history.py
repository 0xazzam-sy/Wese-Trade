"""Historical candle store for replay/backtesting.

Real OKX public candles are fetched with the same parser as the live engine and stored as
gzip CSV (`open_ms,open,high,low,close,volume_base`, closed candles only, ascending) under
`backend/data/history/` (git-ignored). Files can be extended incrementally; loading
validates ordering, uniqueness and contiguity so a backtest never runs on corrupt data.
"""

from __future__ import annotations

import csv
import gzip
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path
from typing import Any

from app.core.runtime import BACKEND_DIR
from app.market_data.models import Candle
from app.market_data.okx import constants as c
from app.market_data.okx.parser import parse_candles, to_inst_id
from app.market_data.okx.rest import OkxRestClient
from app.market_data.services.aggregation import aggregate_history
from app.market_data.timeframes import Timeframe

HISTORY_DIR = BACKEND_DIR / "data" / "history"
HISTORY_PAGE = 100  # documented maximum for /market/history-candles


def history_path(symbol: str, timeframe: Timeframe, root: Path = HISTORY_DIR) -> Path:
    return root / f"{symbol}_{timeframe.value}.csv.gz"


@dataclass(frozen=True, slots=True)
class HistoryInfo:
    symbol: str
    timeframe: str
    candles: int
    first: datetime | None
    last: datetime | None
    gaps: int


def write_history(path: Path, candles: list[Candle]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", newline="") as fh:
        writer = csv.writer(fh)
        for k in candles:
            writer.writerow(
                [
                    k.open_ms,
                    format(k.open, "f"),
                    format(k.high, "f"),
                    format(k.low, "f"),
                    format(k.close, "f"),
                    format(k.volume, "f"),
                ]
            )
    tmp.replace(path)


def read_history(path: Path, symbol: str, timeframe: Timeframe) -> list[Candle]:
    if not path.exists():
        return []
    out: list[Candle] = []
    with gzip.open(path, "rt", newline="") as fh:
        for row in csv.reader(fh):
            out.append(
                Candle(
                    symbol=symbol,
                    timeframe=timeframe,
                    open_time=datetime.fromtimestamp(int(row[0]) / 1000, tz=UTC),
                    open=Decimal(row[1]),
                    high=Decimal(row[2]),
                    low=Decimal(row[3]),
                    close=Decimal(row[4]),
                    volume=Decimal(row[5]),
                    is_closed=True,
                )
            )
    return out


def count_gaps(candles: list[Candle]) -> int:
    if not candles:
        return 0
    step = candles[0].timeframe.milliseconds
    return sum(1 for a, b in pairwise(candles) if b.open_ms - a.open_ms != step)


def validate(candles: list[Candle]) -> None:
    for a, b in pairwise(candles):
        if b.open_ms <= a.open_ms:
            raise ValueError(f"history not strictly ascending at {b.open_time}")


def info(symbol: str, timeframe: Timeframe, root: Path = HISTORY_DIR) -> HistoryInfo:
    candles = load(symbol, timeframe, root)
    return HistoryInfo(
        symbol,
        timeframe.value,
        len(candles),
        candles[0].open_time if candles else None,
        candles[-1].open_time if candles else None,
        count_gaps(candles),
    )


def load(symbol: str, timeframe: Timeframe, root: Path = HISTORY_DIR) -> list[Candle]:
    """Closed candles, ascending. 10m is aggregated from stored 5m (UTC-aligned buckets)."""
    if timeframe.is_synthetic:
        source = read_history(
            history_path(symbol, timeframe.source, root), symbol, timeframe.source
        )
        return [k for k in aggregate_history(source, now_ms=2**62) if k.is_closed]
    candles = read_history(history_path(symbol, timeframe, root), symbol, timeframe)
    validate(candles)
    return candles


async def fetch_range(
    rest: OkxRestClient,
    symbol: str,
    timeframe: Timeframe,
    *,
    start_ms: int,
    end_ms: int,
    progress: Any = None,
) -> list[Candle]:
    """Closed candles with open time in [start_ms, end_ms), paging backwards from end_ms."""
    inst = to_inst_id(symbol)
    bar = c.BARS[timeframe]
    collected: dict[int, Candle] = {}
    after = end_ms
    while after > start_ms:
        rows = await rest.get(
            c.PATH_HISTORY_CANDLES,
            {"instId": inst, "bar": bar, "after": after, "limit": HISTORY_PAGE},
        )
        page = parse_candles(rows, symbol, timeframe)
        if not page:
            break
        for k in page:
            if k.is_closed and start_ms <= k.open_ms < end_ms:
                collected[k.open_ms] = k
        oldest = page[0].open_ms
        if oldest >= after:
            break
        after = oldest
        if progress is not None:
            progress(len(collected))
    return [collected[k] for k in sorted(collected)]


async def extend(
    rest: OkxRestClient,
    symbol: str,
    timeframe: Timeframe,
    *,
    days: int,
    now_ms: int,
    root: Path = HISTORY_DIR,
) -> HistoryInfo:
    """Ensure the file covers [now - days, last closed candle]; fetch only missing ends."""
    path = history_path(symbol, timeframe, root)
    existing = read_history(path, symbol, timeframe)
    step = timeframe.milliseconds
    end = timeframe.bucket_start_ms(now_ms)  # the forming candle is excluded
    start = end - days * 86_400_000
    merged: dict[int, Candle] = {k.open_ms: k for k in existing}
    if not existing or existing[0].open_ms > start:
        older_end = existing[0].open_ms if existing else end
        for k in await fetch_range(rest, symbol, timeframe, start_ms=start, end_ms=older_end):
            merged[k.open_ms] = k
    if existing and existing[-1].open_ms + step < end:
        for k in await fetch_range(
            rest, symbol, timeframe, start_ms=existing[-1].open_ms + step, end_ms=end
        ):
            merged[k.open_ms] = k
    candles = [merged[k] for k in sorted(merged)]
    write_history(path, candles)
    return info(symbol, timeframe, root)


def iter_symbols_timeframes(
    symbols: list[str], timeframes: list[Timeframe]
) -> Iterator[tuple[str, Timeframe]]:
    for s in symbols:
        for tf in timeframes:
            yield s, tf
