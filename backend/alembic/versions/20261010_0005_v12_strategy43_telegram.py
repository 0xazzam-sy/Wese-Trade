"""strategy 4.3 signals and telegram notifications (v1.2)

Revision ID: 0005_v12_strategy43_telegram
Revises: 0004_execution_signals
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_v12_strategy43_telegram"
down_revision: str | None = "0004_execution_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "strategy43_cursors",
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("close_time", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("symbol", "timeframe", name=op.f("pk_strategy43_cursors")),
    )
    op.create_table(
        "strategy43_signals",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("side", sa.Integer(), nullable=False),
        sa.Column("tier", sa.String(length=4), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("family", sa.String(length=32), nullable=False),
        sa.Column("strategy_version", sa.String(length=64), nullable=False),
        sa.Column("candle_time", sa.Integer(), nullable=False),
        sa.Column("confirmed_time", sa.Integer(), nullable=False),
        sa.Column("valid_until", sa.Integer(), nullable=False),
        sa.Column("frozen", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("state_time", sa.Integer(), nullable=False),
        sa.Column("lifecycle", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategy43_signals")),
    )
    with op.batch_alter_table("strategy43_signals", schema=None) as batch_op:
        batch_op.create_index("ix_strategy43_signals_state", ["state"], unique=False)
        batch_op.create_index(
            "ix_strategy43_signals_stream_time",
            ["symbol", "timeframe", "confirmed_time"],
            unique=False,
        )

    op.create_table(
        "telegram_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("signal_id", sa.String(length=160), nullable=False),
        sa.Column("recipient_id", sa.Integer(), nullable=False),
        sa.Column("event", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=255), nullable=False),
        sa.Column("message_id", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("test", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_deliveries")),
        sa.UniqueConstraint("signal_id", "recipient_id", "event", name="uq_telegram_delivery"),
    )
    with op.batch_alter_table("telegram_deliveries", schema=None) as batch_op:
        batch_op.create_index(
            "ix_telegram_deliveries_status", ["status", "created_at"], unique=False
        )

    op.create_table(
        "telegram_recipients",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("chat_id", sa.String(length=64), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("buy", sa.Boolean(), nullable=False),
        sa.Column("sell", sa.Boolean(), nullable=False),
        sa.Column("timeframes", sa.JSON(), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("lifecycle", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_recipients")),
    )
    op.create_table(
        "telegram_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_sealed", sa.Text(), nullable=True),
        sa.Column("token_hint", sa.String(length=16), nullable=False),
        sa.Column("bot_username", sa.String(length=64), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("status_detail", sa.String(length=255), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_telegram_settings")),
    )


def downgrade() -> None:
    op.drop_table("telegram_settings")
    op.drop_table("telegram_recipients")
    with op.batch_alter_table("telegram_deliveries", schema=None) as batch_op:
        batch_op.drop_index("ix_telegram_deliveries_status")

    op.drop_table("telegram_deliveries")
    with op.batch_alter_table("strategy43_signals", schema=None) as batch_op:
        batch_op.drop_index("ix_strategy43_signals_stream_time")
        batch_op.drop_index("ix_strategy43_signals_state")

    op.drop_table("strategy43_signals")
    op.drop_table("strategy43_cursors")
