"""Persisted execution signals (1m / 5m / 10m entry timing, v1.1).

Every row links to its parent Strategy 4.2 signal (strategy, version, signal id, symbol,
timeframe) so each lower-timeframe BUY / SELL is auditable. Frozen terms (plan, reasons,
parent) are written once; later writes touch only lifecycle columns.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime
from app.utils.time import utc_now


class ExecutionSignalRecord(Base):
    __tablename__ = "execution_signals"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    side: Mapped[int] = mapped_column(Integer)
    score: Mapped[float] = mapped_column(Float)
    execution_version: Mapped[str] = mapped_column(String(64))
    parent_strategy: Mapped[str] = mapped_column(String(64))
    parent_strategy_version: Mapped[str] = mapped_column(String(64))
    parent_signal_id: Mapped[str] = mapped_column(String(128))
    parent_symbol: Mapped[str] = mapped_column(String(32))
    parent_timeframe: Mapped[str] = mapped_column(String(8))
    confirmed_time: Mapped[int] = mapped_column(Integer)  # epoch s, close of the trigger candle
    candle_time: Mapped[int] = mapped_column(Integer)  # epoch s, open of the trigger candle
    valid_until: Mapped[int] = mapped_column(Integer)
    frozen: Mapped[dict[str, Any]] = mapped_column(JSON)  # plan, parent, reasons, trigger, micro
    state: Mapped[str] = mapped_column(String(16))
    state_time: Mapped[int] = mapped_column(Integer)
    lifecycle: Mapped[dict[str, Any]] = mapped_column(JSON)  # entered, targets, bars, history
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_execution_signals_stream_time", "symbol", "timeframe", "confirmed_time"),
        Index("ix_execution_signals_parent", "parent_signal_id"),
    )
