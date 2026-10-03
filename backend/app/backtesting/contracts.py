from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from app.market_data.timeframes import Timeframe
from app.signal_engine.contracts import Strategy


@dataclass(frozen=True, slots=True)
class BacktestRequest:
    symbol: str
    timeframe: Timeframe
    start: datetime  # UTC
    end: datetime  # UTC


class BacktestRunner(Protocol):
    async def run(self, request: BacktestRequest, strategy: Strategy) -> str:
        """Start a run and return its id. Results are persisted (future `backtest_runs`)."""
        ...
