"""Regenerate the real-candle fixtures for the frozen forward strategy (BUY + SELL).

Run from backend/ with the Phase 4.1 research store present:

    PYTHONPATH=. python tests/signals/make_frozen_fixtures.py

Each fixture holds OKX ETH-USDT-SWAP 15m candles plus 30m/1h context, enough warm-up
for the analyzer to reproduce the exact signal the research simulator recorded.
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path

from app.market_data.timeframes import Timeframe
from app.research.store import ResearchStore

OUT = Path(__file__).resolve().parents[1] / "fixtures"
SYMBOL = "ETHUSDT"
TICK = 0.01
CASES = {"frozen_buy": (1789707600, 4000), "frozen_sell": (1785499200, 1000)}
AFTER = 8


def main() -> None:
    store = ResearchStore()
    try:
        for name, (trigger, warm) in CASES.items():
            start = (trigger - warm * 900) * 1000
            end = (trigger + AFTER * 900) * 1000
            frames = {"15m": store.load(SYMBOL, Timeframe.M15, start_ms=start, end_ms=end)}
            for ctx in (Timeframe.M30, Timeframe.H1):
                ctx_start = start - warm * ctx.seconds * 1000 // 4
                frames[ctx.value] = store.load(SYMBOL, ctx, start_ms=ctx_start, end_ms=end)
            payload = {
                "symbol": SYMBOL,
                "tick_size": TICK,
                "trigger_time": trigger,
                "frames": {
                    tf: [
                        [
                            c.open_ms,
                            str(c.open),
                            str(c.high),
                            str(c.low),
                            str(c.close),
                            str(c.volume),
                        ]
                        for c in rows
                    ]
                    for tf, rows in frames.items()
                },
            }
            data = json.dumps(payload, separators=(",", ":")).encode()
            (OUT / f"{name}.json.gz").write_bytes(gzip.compress(data, mtime=0))
    finally:
        store.close()


if __name__ == "__main__":
    main()
