"""Telegram notification persistence (v1.2): bot settings, recipients, delivery log.

The bot token is stored only as a sealed ciphertext (`app.core.secretbox`). The delivery
log has one row per (signal id, recipient, event): the unique constraint is the dedupe
guarantee, so a restart never resends an alert that was already queued or delivered.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UTCDateTime
from app.utils.time import utc_now


class TelegramSettingsRecord(Base):
    __tablename__ = "telegram_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # singleton row: 1
    token_sealed: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_hint: Mapped[str] = mapped_column(String(16), default="")
    bot_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    events: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(24), default="not_configured")
    status_detail: Mapped[str] = mapped_column(String(255), default="")
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class TelegramRecipientRecord(Base):
    __tablename__ = "telegram_recipients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64))
    chat_id: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    buy: Mapped[bool] = mapped_column(Boolean, default=True)
    sell: Mapped[bool] = mapped_column(Boolean, default=True)
    timeframes: Mapped[list[str]] = mapped_column(JSON, default=list)  # empty = all
    symbols: Mapped[list[str]] = mapped_column(JSON, default=list)  # empty = all
    lifecycle: Mapped[bool] = mapped_column(Boolean, default=True)  # TP / STOP / EXPIRED alerts
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now, onupdate=utc_now)


class TelegramDeliveryRecord(Base):
    __tablename__ = "telegram_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    signal_id: Mapped[str] = mapped_column(String(160))
    recipient_id: Mapped[int] = mapped_column(Integer)
    event: Mapped[str] = mapped_column(String(16))  # NEW | TP1 | TP2 | TP3 | STOPPED | ...
    symbol: Mapped[str] = mapped_column(String(32), default="")
    timeframe: Mapped[str] = mapped_column(String(8), default="")
    status: Mapped[str] = mapped_column(
        String(16), default="pending"
    )  # pending|sent|failed|skipped
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(255), default="")
    message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    test: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utc_now)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)

    __table_args__ = (
        UniqueConstraint("signal_id", "recipient_id", "event", name="uq_telegram_delivery"),
        Index("ix_telegram_deliveries_status", "status", "created_at"),
    )
