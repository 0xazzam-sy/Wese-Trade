"""Persisted Strategy 4.3 signals (15m / 30m / 1h, v1.2).

One row per confirmed opportunity. The id is stable (symbol, timeframe, side, confirmed
candle), so the live engine, the chart, the execution layer and Telegram all reference
the same canonical signal. Frozen terms are written once; later writes touch only the
lifecycle columns.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Float, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime
from app.utils.time import utc_now


class Strategy43SignalRecord(Base):
    __tablename__ = "strategy43_signals"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    side: Mapped[int] = mapped_column(Integer)
    tier: Mapped[str] = mapped_column(String(4))
    score: Mapped[float] = mapped_column(Float)
    family: Mapped[str] = mapped_column(String(32))
    strategy_version: Mapped[str] = mapped_column(String(64))
    candle_time: Mapped[int] = mapped_column(Integer)  # epoch s, open of the trigger candle
    confirmed_time: Mapped[int] = mapped_column(Integer)  # epoch s, close of the trigger candle
    valid_until: Mapped[int] = mapped_column(Integer)  # entry window end
    frozen: Mapped[dict[str, Any]] = mapped_column(JSON)  # plan, scores, reasons, regime
    state: Mapped[str] = mapped_column(String(16))
    state_time: Mapped[int] = mapped_column(Integer)
    lifecycle: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_strategy43_signals_stream_time", "symbol", "timeframe", "confirmed_time"),
        Index("ix_strategy43_signals_state", "state"),
    )


class Strategy43CursorRecord(Base):
    """Last processed closed candle per stream: candles closed while the app was down only
    advance open signals after a restart; they never create new ones."""

    __tablename__ = "strategy43_cursors"

    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    close_time: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)
