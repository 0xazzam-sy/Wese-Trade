"""Optional real-market analysis checks against the OKX PUBLIC API (no credentials).

Skipped by default. Run with:  pytest -m live_analysis
Asserts structural sanity only — never fragile, market-specific event counts.
"""

from __future__ import annotations

import asyncio
import time
from itertools import pairwise

import pytest

from app.analysis.engine import MarketAnalyzer
from app.analysis.serialize import snapshot_payload
from app.market_data.models import Candle
from app.market_data.okx.provider import OkxProvider
from app.market_data.okx.rest import OkxRestClient
from app.market_data.okx.stream import OkxSocket
from app.market_data.timeframes import Timeframe

pytestmark = pytest.mark.live_analysis

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
TIMEFRAMES = (Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1)


History = dict[tuple[str, Timeframe], tuple[list[Candle], float]]


async def _fetch() -> History:
    provider = OkxProvider(
        OkxRestClient("https://openapi.okx.com"),
        OkxSocket("public", "wss://ws.okx.com/ws/v5/public"),
        OkxSocket("business", "wss://ws.okx.com/ws/v5/business"),
    )
    try:
        markets = {s.symbol: s for s in await provider.list_symbols()}
        data: History = {}
        for name in SYMBOLS:
            for tf in TIMEFRAMES:
                candles = await provider.fetch_candles(markets[name], tf, limit=1000)
                data[(name, tf)] = (candles, float(markets[name].tick_size))
        return data
    finally:
        await provider.close()


@pytest.fixture(scope="module")
def history() -> History:
    return asyncio.run(_fetch())


def _ids(items: list[dict]) -> list[str]:  # type: ignore[type-arg]
    return [i["id"] for i in items]


@pytest.mark.parametrize("name", SYMBOLS)
@pytest.mark.parametrize("tf", TIMEFRAMES)
def test_real_market_analysis_is_sane(history: History, name: str, tf: Timeframe) -> None:
    candles, tick = history[(name, tf)]
    closed = [c for c in candles if c.is_closed]
    forming = next((c for c in candles if not c.is_closed), None)
    analyzer = MarketAnalyzer(name, tf, tick_size=tick)
    for c in closed:
        analyzer.update(c)
    snap = snapshot_payload(analyzer.snapshot(forming, context=[], include_debug=True))
    assert snap["analysis_ready"] is True
    now = time.time()
    last_close = closed[-1].open_ms // 1000 + tf.seconds
    assert 0 <= snap["momentum"]["rsi"] <= 100
    assert snap["volatility"]["atr"] > 0
    assert 0 <= snap["volatility"]["atr_percentile"] <= 100
    for layer in ("swing_structure", "internal_structure"):
        state = snap[layer]
        events, pivots = state["events"], state["pivots"]
        assert [e["time"] for e in events] == sorted(e["time"] for e in events)
        assert len(set(_ids(events))) == len(events) and len(set(_ids(pivots))) == len(pivots)
        for item in [*events, *pivots]:
            assert item["time"] < item["confirmed_time"] <= last_close <= now + tf.seconds
        for a, b in pairwise(pivots):
            assert a["confirmed_time"] <= b["confirmed_time"]
    for zone in [*snap["fair_value_gaps"], *snap["order_blocks"]]:
        assert zone["top"] > zone["bottom"] and 0 <= zone["quality"] <= 100
        assert zone["confirmed_time"] <= last_close
    for sweep in snap["liquidity"]["sweeps"]:
        assert sweep["confirmed_time"] <= last_close and 0 <= sweep["quality"] <= 100
    pd = snap["premium_discount"]
    if pd is not None:
        assert pd["high"] > pd["low"]

    # Confirmed facts known 60 candles ago are unchanged now (no repaint on real data).
    earlier = MarketAnalyzer(name, tf, tick_size=tick)
    for c in closed[:-60]:
        earlier.update(c)
    then = {e.id: e for e in [*earlier.swing.events, *earlier.internal.events]}
    now_events = {e.id: e for e in [*analyzer.swing.events, *analyzer.internal.events]}
    for key, event in then.items():
        assert now_events[key] == event
