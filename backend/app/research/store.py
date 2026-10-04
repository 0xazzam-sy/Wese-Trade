"""Local historical research store (SQLite), separate from the app database.

One row per (symbol, timeframe, open time): OHLCV as exact decimal strings, the closed
flag and the data source. Inserts are idempotent: an existing row is never overwritten,
and a re-download that disagrees with stored values is counted as a conflict (exchange
history should be immutable once a candle is closed). Only closed candles are stored.

Funding-rate history is stored in its own table for the funding/OI study. Nothing here is
mixed with live signal persistence.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

from app.core.config import BACKEND_DIR
from app.market_data.models import Candle
from app.market_data.services.aggregation import aggregate_history
from app.market_data.timeframes import Timeframe

RESEARCH_DIR = BACKEND_DIR / "data" / "research"
STORE_PATH = RESEARCH_DIR / "candles.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol     TEXT    NOT NULL,
    timeframe  TEXT    NOT NULL,
    open_ms    INTEGER NOT NULL,
    open       TEXT    NOT NULL,
    high       TEXT    NOT NULL,
    low        TEXT    NOT NULL,
    close      TEXT    NOT NULL,
    volume     TEXT    NOT NULL,
    closed     INTEGER NOT NULL CHECK (closed = 1),
    source     TEXT    NOT NULL,
    fetched_ms INTEGER NOT NULL,
    PRIMARY KEY (symbol, timeframe, open_ms)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS research_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT    NOT NULL,
    created_ms       INTEGER NOT NULL,
    baseline_version TEXT    NOT NULL,
    analysis_version TEXT    NOT NULL,
    metadata         TEXT    NOT NULL,  -- JSON: data periods, symbols, timeframes, costs, windows
    results          TEXT    NOT NULL   -- JSON: aggregate / per-window / grouped / calibration
);
CREATE TABLE IF NOT EXISTS funding (
    symbol      TEXT    NOT NULL,
    funding_ms  INTEGER NOT NULL,
    rate        TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    PRIMARY KEY (symbol, funding_ms)
) WITHOUT ROWID;
"""


@dataclass(frozen=True, slots=True)
class Coverage:
    symbol: str
    timeframe: str
    candles: int
    first_ms: int | None
    last_ms: int | None
    gaps: int

    @property
    def days(self) -> float:
        if self.first_ms is None or self.last_ms is None:
            return 0.0
        return (self.last_ms - self.first_ms) / 86_400_000


@dataclass(frozen=True, slots=True)
class InsertResult:
    inserted: int
    duplicates: int
    conflicts: int


class ResearchStore:
    def __init__(self, path: Path = STORE_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(path)
        self._conn.executescript(SCHEMA)
        self._conn.execute("PRAGMA journal_mode=WAL")

    def close(self) -> None:
        self._conn.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._conn:
            yield self._conn

    # --- candles -------------------------------------------------------------------------
    def insert(self, candles: Iterable[Candle], source: str) -> InsertResult:
        """Insert closed candles; duplicates are ignored, disagreeing duplicates counted."""
        rows = [
            (
                k.symbol,
                k.timeframe.value,
                k.open_ms,
                format(k.open, "f"),
                format(k.high, "f"),
                format(k.low, "f"),
                format(k.close, "f"),
                format(k.volume, "f"),
            )
            for k in candles
            if k.is_closed
        ]
        if not rows:
            return InsertResult(0, 0, 0)
        now = int(time.time() * 1000)
        inserted = duplicates = conflicts = 0
        with self._tx() as conn:
            for row in rows:
                cur = conn.execute(
                    "INSERT OR IGNORE INTO candles VALUES (?,?,?,?,?,?,?,?,1,?,?)",
                    (*row, source, now),
                )
                if cur.rowcount:
                    inserted += 1
                    continue
                duplicates += 1
                stored = conn.execute(
                    "SELECT open, high, low, close, volume FROM candles "
                    "WHERE symbol=? AND timeframe=? AND open_ms=?",
                    row[:3],
                ).fetchone()
                if stored is not None and tuple(Decimal(v) for v in stored) != tuple(
                    Decimal(v) for v in row[3:]
                ):
                    conflicts += 1
        return InsertResult(inserted, duplicates, conflicts)

    def load(
        self,
        symbol: str,
        timeframe: Timeframe,
        *,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[Candle]:
        """Closed candles ascending; synthetic timeframes (10m) are aggregated from 5m."""
        if timeframe.is_synthetic:
            source = self.load(symbol, timeframe.source, start_ms=start_ms, end_ms=end_ms)
            return [k for k in aggregate_history(source, now_ms=2**62) if k.is_closed]
        query = (
            "SELECT open_ms, open, high, low, close, volume FROM candles "
            "WHERE symbol=? AND timeframe=?"
        )
        params: list[object] = [symbol, timeframe.value]
        if start_ms is not None:
            query += " AND open_ms >= ?"
            params.append(start_ms)
        if end_ms is not None:
            query += " AND open_ms < ?"
            params.append(end_ms)
        query += " ORDER BY open_ms"
        return [
            Candle(
                symbol=symbol,
                timeframe=timeframe,
                open_time=datetime.fromtimestamp(ms / 1000, tz=UTC),
                open=Decimal(o),
                high=Decimal(h),
                low=Decimal(lo),
                close=Decimal(c),
                volume=Decimal(v),
                is_closed=True,
            )
            for ms, o, h, lo, c, v in self._conn.execute(query, params)
        ]

    def coverage(self, symbol: str, timeframe: Timeframe) -> Coverage:
        rows = [
            r[0]
            for r in self._conn.execute(
                "SELECT open_ms FROM candles WHERE symbol=? AND timeframe=? ORDER BY open_ms",
                (symbol, timeframe.value),
            )
        ]
        step = timeframe.milliseconds
        gaps = sum(1 for a, b in pairwise(rows) if b - a != step)
        return Coverage(
            symbol,
            timeframe.value,
            len(rows),
            rows[0] if rows else None,
            rows[-1] if rows else None,
            gaps,
        )

    def symbols(self) -> list[tuple[str, str, int]]:
        return list(
            self._conn.execute(
                "SELECT symbol, timeframe, COUNT(*) FROM candles GROUP BY symbol, timeframe "
                "ORDER BY symbol, timeframe"
            )
        )

    # --- research runs -----------------------------------------------------------------------
    def save_run(
        self,
        name: str,
        *,
        baseline_version: str,
        analysis_version: str,
        metadata: dict[str, object],
        results: dict[str, object],
    ) -> int:
        with self._tx() as conn:
            cur = conn.execute(
                "INSERT INTO research_runs (name, created_ms, baseline_version, analysis_version, "
                "metadata, results) VALUES (?,?,?,?,?,?)",
                (
                    name,
                    int(time.time() * 1000),
                    baseline_version,
                    analysis_version,
                    json.dumps(metadata, default=str),
                    json.dumps(results, default=str),
                ),
            )
            return int(cur.lastrowid or 0)

    def runs(self) -> list[dict[str, object]]:
        return [
            {"id": i, "name": n, "created_ms": c, "baseline_version": b}
            for i, n, c, b in self._conn.execute(
                "SELECT id, name, created_ms, baseline_version FROM research_runs ORDER BY id DESC"
            )
        ]

    def run(self, run_id: int) -> dict[str, object] | None:
        row = self._conn.execute(
            "SELECT id, name, created_ms, baseline_version, analysis_version, metadata, results "
            "FROM research_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "name": row[1],
            "created_ms": row[2],
            "baseline_version": row[3],
            "analysis_version": row[4],
            "metadata": json.loads(row[5]),
            "results": json.loads(row[6]),
        }

    # --- funding ----------------------------------------------------------------------------
    def insert_funding(self, symbol: str, rows: Iterable[tuple[int, str]], source: str) -> int:
        with self._tx() as conn:
            before = conn.total_changes
            conn.executemany(
                "INSERT OR IGNORE INTO funding VALUES (?,?,?,?)",
                [(symbol, ms, rate, source) for ms, rate in rows],
            )
            return conn.total_changes - before

    def load_funding(self, symbol: str) -> list[tuple[int, float]]:
        return [
            (ms, float(rate))
            for ms, rate in self._conn.execute(
                "SELECT funding_ms, rate FROM funding WHERE symbol=? ORDER BY funding_ms",
                (symbol,),
            )
        ]
