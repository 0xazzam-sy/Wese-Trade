"""Backtesting contracts. The implementation is app.backtesting.runner (sequential replay
with the canonical MarketAnalyzer + SignalEngine + SignalTracker) and report.py."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.market_data.timeframes import Timeframe


@dataclass(frozen=True, slots=True)
class BacktestRequest:
    symbol: str
    timeframe: Timeframe
    start: datetime  # UTC
    end: datetime  # UTC
