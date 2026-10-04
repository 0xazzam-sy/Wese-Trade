from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.market_data.timeframes import Timeframe
from app.signal_engine.enums import SignalClass


@dataclass(frozen=True, slots=True)
class ScannerRow:
    symbol: str
    timeframe: Timeframe
    last_price: Decimal
    signal_class: SignalClass | None
    score: float | None  # confluence score /100, not a probability
