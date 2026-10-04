"""Download real OKX public candles for backtesting (no credentials).

    python -m app.scripts.fetch_history --symbols BTCUSDT ETHUSDT SOLUSDT

Default depth per native timeframe (10m is aggregated from 5m when loading):
1m 60d, 5m 180d, 15m 365d, 30m 730d, 1h 1095d. Re-running extends existing files.
"""

from __future__ import annotations

import argparse
import asyncio
import time

from app.backtesting.history import extend
from app.core.config import get_settings
from app.market_data.okx.rest import OkxRestClient
from app.market_data.timeframes import Timeframe

DEFAULT_DAYS = {
    Timeframe.M1: 60,
    Timeframe.M5: 180,
    Timeframe.M15: 365,
    Timeframe.M30: 730,
    Timeframe.H1: 1095,
}


async def main(symbols: list[str], timeframes: list[Timeframe], scale: float) -> None:
    rest = OkxRestClient(get_settings().okx_rest_url)
    try:
        now_ms = int(time.time() * 1000)
        for symbol in symbols:
            for tf in timeframes:
                started = time.monotonic()
                result = await extend(
                    rest, symbol, tf, days=max(1, int(DEFAULT_DAYS[tf] * scale)), now_ms=now_ms
                )
                print(
                    f"{symbol} {tf.value}: {result.candles} candles "
                    f"{result.first:%Y-%m-%d} -> {result.last:%Y-%m-%d %H:%M} "
                    f"gaps={result.gaps} ({time.monotonic() - started:.0f}s)",
                    flush=True,
                )
    finally:
        await rest.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    parser.add_argument("--timeframes", nargs="+", default=[tf.value for tf in DEFAULT_DAYS])
    parser.add_argument("--scale", type=float, default=1.0, help="multiply default depths")
    args = parser.parse_args()
    asyncio.run(main(args.symbols, [Timeframe(t) for t in args.timeframes], args.scale))
