"""Builders for analysis tests: handcrafted candle paths and real OKX fixtures."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import pairwise
from pathlib import Path

from app.analysis.config import AnalysisConfig
from app.analysis.engine import MarketAnalyzer
from app.market_data.models import Candle
from app.market_data.timeframes import Timeframe

T0 = datetime(2026, 10, 1, tzinfo=UTC)
DATA = Path(__file__).parent / "data"

# Small periods so handcrafted paths of a few dozen candles are "ready".
SMALL = AnalysisConfig(
    ema_periods=(2, 3, 4, 5),
    atr_period=3,
    atr_percentile_window=10,
    rsi_period=3,
    roc_period=3,
    accel_period=2,
    volume_lookback=3,
    volume_percentile_window=10,
    efficiency_window=5,
    range_compression_short=3,
    range_compression_long=10,
    swing_left=2,
    swing_right=2,
    internal_left=1,
    internal_right=1,
    min_candles=10,
    ob_min_displacement=0.0,
    fvg_min_atr=0.1,
)


def candle(
    i: int,
    o: float,
    h: float,
    lo: float,
    c: float,
    *,
    v: float = 10.0,
    tf: Timeframe = Timeframe.M1,
    closed: bool = True,
    symbol: str = "BTCUSDT",
) -> Candle:
    return Candle(
        symbol=symbol,
        timeframe=tf,
        open_time=T0 + timedelta(seconds=i * tf.seconds),
        open=Decimal(str(o)),
        high=Decimal(str(h)),
        low=Decimal(str(lo)),
        close=Decimal(str(c)),
        volume=Decimal(str(v)),
        is_closed=closed,
    )


def ohlc(rows: Sequence[tuple[float, float, float, float]], **kw: object) -> list[Candle]:
    return [candle(i, *row, **kw) for i, row in enumerate(rows)]  # type: ignore[arg-type]


def path(closes: Sequence[float], wick: float = 0.5, v: float = 10.0) -> list[Candle]:
    """Open = previous close; wicks of `wick` beyond the body."""
    out: list[Candle] = []
    prev = closes[0]
    for i, c in enumerate(closes):
        o = prev
        out.append(candle(i, o, max(o, c) + wick, min(o, c) - wick, c, v=v))
        prev = c
    return out


def zigzag(legs: Sequence[float], steps: int = 4, wick: float = 0.3) -> list[Candle]:
    """Piecewise-linear closes through the given turning points."""
    closes: list[float] = [legs[0]]
    for a, b in pairwise(legs):
        closes += [a + (b - a) * k / steps for k in range(1, steps + 1)]
    return path(closes, wick=wick)


def load_fixture(name: str) -> tuple[list[Candle], float]:
    raw = json.loads((DATA / f"{name}.json").read_text())
    tf = Timeframe(raw["timeframe"])
    candles = [
        Candle(
            symbol=raw["symbol"],
            timeframe=tf,
            open_time=datetime.fromtimestamp(r[0] / 1000, tz=UTC),
            open=Decimal(r[1]),
            high=Decimal(r[2]),
            low=Decimal(r[3]),
            close=Decimal(r[4]),
            volume=Decimal(r[5]),
            is_closed=True,
        )
        for r in raw["rows"]
    ]
    return candles, float(raw["tick_size"])


def run(
    candles: Sequence[Candle],
    config: AnalysisConfig = SMALL,
    tick: float = 0.01,
) -> MarketAnalyzer:
    first = candles[0]
    analyzer = MarketAnalyzer(first.symbol, first.timeframe, tick_size=tick, config=config)
    for c in candles:
        analyzer.update(c)
    return analyzer


def forming(c: Candle) -> Candle:
    return replace(c, is_closed=False)
