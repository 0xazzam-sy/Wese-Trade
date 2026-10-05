"""Prospective forward-test persistence (Phase 4.2).

Kept separate from the research store (data/research) and from the live baseline
`signals` table, so prospective metrics can never mix with historical ones.

* forward_test_runs        one row per run; config is frozen at start (immutable)
* forward_test_signals     every CONFIRMED forward-test signal: frozen terms + lifecycle
* forward_test_outcomes    one row per closed signal: R results, costs, holding time
* forward_test_cursors     last processed closed candle per (run, symbol, timeframe)
* forward_test_checkpoints periodic (daily) metric snapshots
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime
from app.utils.time import utc_now


class ForwardTestRun(Base):
    __tablename__ = "forward_test_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    strategy_version: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(32))
    research_version: Mapped[str] = mapped_column(String(64))
    config: Mapped[dict[str, Any]] = mapped_column(JSON)  # frozen at start, never updated
    started_at: Mapped[datetime] = mapped_column(UTCDateTime())
    stopped_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    # forward_testing | paused | stopped | passed_forward_test | failed_forward_test
    status: Mapped[str] = mapped_column(String(32))
    symbols: Mapped[list[str]] = mapped_column(JSON)
    timeframes: Mapped[list[str]] = mapped_column(JSON)
    cost_model: Mapped[dict[str, Any]] = mapped_column(JSON)
    minimum_required_trades: Mapped[int] = mapped_column(Integer)
    minimum_days: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str] = mapped_column(Text, default="")
    status_history: Mapped[list[Any]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    __table_args__ = (
        # Only ONE open (not stopped/concluded) run per strategy version.
        Index(
            "uq_forward_test_runs_open_version",
            "strategy_version",
            unique=True,
            sqlite_where=stopped_at.is_(None),
            postgresql_where=stopped_at.is_(None),
        ),
    )


class ForwardTestSignal(Base):
    __tablename__ = "forward_test_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("forward_test_runs.id", ondelete="CASCADE"))
    signal_id: Mapped[str] = mapped_column(String(64))
    strategy_version: Mapped[str] = mapped_column(String(64))
    # --- frozen at confirmation (never updated) ---------------------------------------------
    symbol: Mapped[str] = mapped_column(String(32))
    timeframe: Mapped[str] = mapped_column(String(8))
    side: Mapped[str] = mapped_column(String(8))
    signal_class: Mapped[str] = mapped_column(String(16))
    family: Mapped[str] = mapped_column(String(32))
    score: Mapped[float] = mapped_column(Float)
    regime: Mapped[str | None] = mapped_column(String(32), default=None)
    confirmed_at: Mapped[datetime] = mapped_column(UTCDateTime())
    entry_model: Mapped[str] = mapped_column(String(16))
    entry: Mapped[float] = mapped_column(Float)
    stop: Mapped[float] = mapped_column(Float)
    tp1: Mapped[float] = mapped_column(Float)
    tp2: Mapped[float] = mapped_column(Float)
    tp3: Mapped[float] = mapped_column(Float)
    frozen: Mapped[dict[str, Any]] = mapped_column(JSON)  # full frozen terms + reasons/evidence
    # --- lifecycle (forward-only updates) ----------------------------------------------------
    state: Mapped[str] = mapped_column(String(16))
    state_at: Mapped[datetime] = mapped_column(UTCDateTime())
    entered_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    entry_price: Mapped[float | None] = mapped_column(Float, default=None)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), default=None)
    lifecycle: Mapped[dict[str, Any]] = mapped_column(JSON)  # exits, remaining, bars, history
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("uq_forward_test_signal", "run_id", "signal_id", unique=True),
        Index("ix_forward_test_signals_stream", "run_id", "symbol", "timeframe", "confirmed_at"),
    )


class ForwardTestOutcome(Base):
    __tablename__ = "forward_test_outcomes"

    signal_pk: Mapped[int] = mapped_column(
        ForeignKey("forward_test_signals.id", ondelete="CASCADE"), primary_key=True
    )
    run_id: Mapped[int] = mapped_column(ForeignKey("forward_test_runs.id", ondelete="CASCADE"))
    outcome: Mapped[str] = mapped_column(String(16))  # final state
    exit_reason: Mapped[str | None] = mapped_column(String(32), default=None)
    entered: Mapped[bool] = mapped_column(Boolean)
    gross_r: Mapped[float | None] = mapped_column(Float, default=None)
    net_r: Mapped[float | None] = mapped_column(Float, default=None)
    fees_r: Mapped[float | None] = mapped_column(Float, default=None)
    slippage_r: Mapped[float | None] = mapped_column(Float, default=None)
    holding_bars: Mapped[int] = mapped_column(Integer, default=0)
    targets_hit: Mapped[int] = mapped_column(Integer, default=0)
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False)
    closed_at: Mapped[datetime] = mapped_column(UTCDateTime())


class ForwardTestCursor(Base):
    __tablename__ = "forward_test_cursors"

    run_id: Mapped[int] = mapped_column(
        ForeignKey("forward_test_runs.id", ondelete="CASCADE"), primary_key=True
    )
    symbol: Mapped[str] = mapped_column(String(32), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    last_close_time: Mapped[int] = mapped_column(Integer)  # epoch seconds
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class ForwardTestCheckpoint(Base):
    __tablename__ = "forward_test_checkpoints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("forward_test_runs.id", ondelete="CASCADE"))
    day: Mapped[date] = mapped_column(Date)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)

    __table_args__ = (Index("uq_forward_test_checkpoint_day", "run_id", "day", unique=True),)
