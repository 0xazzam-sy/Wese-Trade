"""Build the Phase 4.1 research data set from REAL OKX public data (no credentials).

    python -m app.scripts.research_fetch --select          # choose + save the universe
    python -m app.scripts.research_fetch                   # import CSVs, fetch missing history

Data lands in data/research/candles.sqlite (git-ignored), deduplicated per
(symbol, timeframe, open time). Only missing ranges are requested; requests are paced by
the shared OKX token bucket (history-candles: 100 candles per request).
"""

from __future__ import annotations

import argparse
import asyncio
import time
from typing import Any

from app.backtesting.history import HISTORY_DIR, HISTORY_PAGE, read_history
from app.core.config import get_settings
from app.market_data.exceptions import ProviderRateLimited
from app.market_data.okx import constants as c
from app.market_data.okx.parser import parse_candles, to_inst_id
from app.market_data.okx.rest import OkxRestClient
from app.market_data.timeframes import Timeframe
from app.research import universe
from app.research.store import ResearchStore

# Research depth (days back from now) per native timeframe. 1m only for the anchors.
DEPTH_DAYS = {Timeframe.M5: 365, Timeframe.M15: 365, Timeframe.M30: 365, Timeframe.H1: 730}
ANCHOR_DEPTH_DAYS = {Timeframe.M1: 180, **DEPTH_DAYS}
# Phase 5 lower-timeframe research: 2 years of 5m (15m/30m/1h context and 10m are
# aggregated from it) and 365 days of 1m, for EVERY universe member (not only anchors).
LTF_DEPTH_DAYS = {Timeframe.M5: 730, Timeframe.M1: 365}
SOURCE = "okx:history-candles"


def import_csvs(store: ResearchStore) -> None:
    for path in sorted(HISTORY_DIR.glob("*.csv.gz")):
        symbol, tf_value = path.name.removesuffix(".csv.gz").split("_")
        tf = Timeframe(tf_value)
        result = store.insert(read_history(path, symbol, tf), f"{SOURCE} (phase4 csv)")
        print(
            f"import {path.name}: +{result.inserted} dup={result.duplicates} "
            f"conflicts={result.conflicts}"
        )


async def _get(rest: OkxRestClient, path: str, params: dict[str, str | int]) -> Any:
    """GET with patient retries on rate limiting (research downloads are not urgent)."""
    for attempt in range(20):
        try:
            return await rest.get(path, params)
        except ProviderRateLimited as exc:
            await asyncio.sleep(max(exc.retry_after, 2.0) * (1 + attempt / 4))
    raise RuntimeError(f"still rate limited after retries: {path}")


async def fetch_into_store(
    store: ResearchStore,
    rest: OkxRestClient,
    symbol: str,
    tf: Timeframe,
    start_ms: int,
    end_ms: int,
) -> None:
    """Page backwards from end_ms to start_ms, inserting every page (resumable)."""
    after = end_ms
    while after > start_ms:
        rows = await _get(
            rest,
            c.PATH_HISTORY_CANDLES,
            {
                "instId": to_inst_id(symbol),
                "bar": c.BARS[tf],
                "after": after,
                "limit": HISTORY_PAGE,
            },
        )
        page = parse_candles(rows, symbol, tf)
        if not page:
            break
        result = store.insert((k for k in page if start_ms <= k.open_ms < end_ms), SOURCE)
        if result.conflicts:
            print(
                f"  WARNING {symbol} {tf.value}: {result.conflicts} conflicting candles "
                "kept as stored"
            )
        oldest = page[0].open_ms
        if oldest >= after:
            break
        after = oldest


async def ensure(
    store: ResearchStore, rest: OkxRestClient, symbol: str, tf: Timeframe, days: int, now_ms: int
) -> None:
    started = time.monotonic()
    end = tf.bucket_start_ms(now_ms)
    start = end - days * 86_400_000
    cov = store.coverage(symbol, tf)
    ranges = []
    if cov.first_ms is None:
        ranges.append((start, end))
    else:
        if cov.first_ms > start:
            ranges.append((start, cov.first_ms))
        if cov.last_ms is not None and cov.last_ms + tf.milliseconds < end:
            ranges.append((cov.last_ms + tf.milliseconds, end))
    for lo, hi in ranges:
        await fetch_into_store(store, rest, symbol, tf, lo, hi)
    cov = store.coverage(symbol, tf)
    print(
        f"{symbol:>14} {tf.value:>3}: {cov.candles:>7} candles, {cov.days:6.0f} days, "
        f"gaps={cov.gaps} ({time.monotonic() - started:.0f}s)",
        flush=True,
    )


async def fetch_funding(
    store: ResearchStore, rest: OkxRestClient, member: universe.UniverseMember
) -> None:
    after: str | None = None
    total = 0
    while True:
        params: dict[str, str | int] = {"instId": member.inst_id, "limit": 100}
        if after:
            params["after"] = after
        rows = await _get(rest, "/api/v5/public/funding-rate-history", params)
        if not rows:
            break
        total += store.insert_funding(
            member.symbol,
            [(int(r["fundingTime"]), r["realizedRate"] or r["fundingRate"]) for r in rows],
            "okx:funding-rate-history",
        )
        if after == rows[-1]["fundingTime"]:
            break
        after = rows[-1]["fundingTime"]
    print(f"{member.symbol:>14} funding: +{total}")


async def main(select: bool, skip_import: bool, ltf: bool = False) -> None:
    # Slower than the live client: history endpoints have tighter per-endpoint limits.
    rest = OkxRestClient(get_settings().okx_rest_url, rate_per_second=5.0, burst=5)
    store = ResearchStore()
    try:
        if select:
            members = await universe.select(rest)
            universe.save(
                members,
                rule="anchors + 9 most liquid (30d mean quote volume), listed >= 400d, crypto only",
            )
            for m in members:
                print(
                    f"{m.symbol:>14} {m.mean_daily_quote_volume / 1e6:10.1f}M/day anchor={m.anchor}"
                )
            return
        if not skip_import:
            import_csvs(store)
        now_ms = int(time.time() * 1000)
        # A few series in flight at once; the client's shared token bucket still caps the
        # total request rate (8/s, below OKX's 20 per 2 s for history-candles).
        gate = asyncio.Semaphore(2)

        async def one(member: universe.UniverseMember) -> None:
            async with gate:
                if ltf:
                    depth = LTF_DEPTH_DAYS
                else:
                    depth = ANCHOR_DEPTH_DAYS if member.anchor else DEPTH_DAYS
                for tf, days in depth.items():
                    await ensure(store, rest, member.symbol, tf, days, now_ms)
                if not ltf:
                    await fetch_funding(store, rest, member)

        await asyncio.gather(*(one(m) for m in universe.load()))
    finally:
        store.close()
        await rest.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--select", action="store_true")
    parser.add_argument("--skip-import", action="store_true")
    parser.add_argument("--ltf", action="store_true", help="Phase 5 lower-timeframe depth")
    args = parser.parse_args()
    asyncio.run(main(args.select, args.skip_import, args.ltf))
