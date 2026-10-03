from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.market_data.timeframes import Timeframe
from app.signal_engine.contracts import SignalLabel


@dataclass(frozen=True, slots=True)
class ScannerRow:
    symbol: str
    timeframe: Timeframe
    last_price: Decimal
    label: SignalLabel | None
    confidence: int | None  # confluence score, not a probability
