"""Domain contracts for future signal generation.

IMPORTANT: `confidence` is a strategy confluence score (0-100). It is NOT a probability that
a trade will win and must never be presented as one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from app.market_data.models import Candle
from app.market_data.timeframes import Timeframe


class SignalLabel(StrEnum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


class SignalState(StrEnum):
    DEVELOPING = "developing"  # conditions forming on an open candle; may change
    CONFIRMED = "confirmed"  # conditions held at candle close
    INVALIDATED = "invalidated"  # setup broke before entry
    CLOSED = "closed"  # trade plan finished (TP/SL/expiry)


@dataclass(frozen=True, slots=True)
class TradePlan:
    entry: Decimal
    stop_loss: Decimal
    take_profits: tuple[Decimal, Decimal, Decimal]  # TP1, TP2, TP3
    risk_reward: Decimal  # computed from entry/SL/TP, rounded per symbol metadata


@dataclass(frozen=True, slots=True)
class Signal:
    symbol: str
    timeframe: Timeframe
    label: SignalLabel
    state: SignalState
    confidence: int  # 0-100 confluence score, NOT a win probability
    plan: TradePlan | None  # None for NEUTRAL
    generated_at: datetime  # UTC
    candle_open_time: datetime  # UTC open time of the evaluated candle
    strategy_version: str


@dataclass(frozen=True, slots=True)
class MarketContext:
    """Everything a strategy may read. Deterministic, no wall-clock or network access."""

    symbol: str
    timeframe: Timeframe
    candles: Sequence[Candle]  # closed candles, oldest first (+ optional forming candle)
    higher_timeframes: dict[Timeframe, Sequence[Candle]]


class Strategy(Protocol):
    """Pure evaluation function shared by the live engine and the backtester."""

    version: str

    def evaluate(self, context: MarketContext) -> Signal | None: ...
