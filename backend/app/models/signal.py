"""Persisted signals (audit trail), their outcomes, and backtest runs.

Only CONFIRMED signals are stored (never developing ticks). Each row keeps enough evidence
to answer "why did Wese Trade issue this?": component scores, penalties, Arabic reasons,
the compact feature evidence, the frozen trade plan and the strategy version.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime
from app.utils.time import utc_now


class SignalRecord(Base):
    __tablename__ = "signals"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source: Mapped[str] = mapped_column(String(16), default="live")  # live | backtest
    symbol: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    side: Mapped[str] = mapped_column(String(8))
    signal_class: Mapped[str] = mapped_column(String(16))
    family: Mapped[str] = mapped_column(String(32))
    score: Mapped[float] = mapped_column(Float)
    strategy_version: Mapped[str] = mapped_column(String(64))
    trigger_id: Mapped[str] = mapped_column(String(128))
    trigger_at: Mapped[datetime] = mapped_column(UTCDateTime())
    confirmed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    plan: Mapped[dict[str, Any]] = mapped_column(JSON)
    components: Mapped[list[Any]] = mapped_column(JSON)
    penalties: Mapped[list[Any]] = mapped_column(JSON)
    reasons: Mapped[dict[str, Any]] = mapped_column(JSON)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(16))
    state_at: Mapped[datetime] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)

    __table_args__ = (Index("ix_signals_stream_time", "symbol", "timeframe", "confirmed_at"),)


class SignalOutcomeRecord(Base):
    __tablename__ = "signal_outcomes"

    signal_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("signals.id", ondelete="CASCADE"), primary_key=True
    )
    entered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    entry_price: Mapped[float | None] = mapped_column(Float, default=None)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    exit_reason: Mapped[str | None] = mapped_column(String(32), default=None)
    targets_hit: Mapped[int] = mapped_column(Integer, default=0)
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)
    gross_r: Mapped[float | None] = mapped_column(Float, default=None)
    net_r: Mapped[float | None] = mapped_column(Float, default=None)
    mfe_r: Mapped[float] = mapped_column(Float, default=0.0)
    mae_r: Mapped[float] = mapped_column(Float, default=0.0)
    bars_held: Mapped[int] = mapped_column(Integer, default=0)
    exits: Mapped[list[Any]] = mapped_column(JSON, default=list)
    history: Mapped[list[Any]] = mapped_column(JSON, default=list)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class BacktestRunRecord(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    strategy_version: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    config: Mapped[dict[str, Any]] = mapped_column(JSON)
    data: Mapped[list[Any]] = mapped_column(JSON)
    summary: Mapped[dict[str, Any]] = mapped_column(JSON)  # all / dev / holdout reports
