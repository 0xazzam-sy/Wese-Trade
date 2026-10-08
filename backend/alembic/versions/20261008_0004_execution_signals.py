"""execution signals: 1m/5m/10m entry timing linked to Strategy 4.2 parents (v1.1)

Revision ID: 0004_execution_signals
Revises: 0003_forward_test
Create Date: 2026-10-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_execution_signals"
down_revision: str | None = "0003_forward_test"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "execution_signals",
        sa.Column("id", sa.String(length=128), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("side", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("execution_version", sa.String(length=64), nullable=False),
        sa.Column("parent_strategy", sa.String(length=64), nullable=False),
        sa.Column("parent_strategy_version", sa.String(length=64), nullable=False),
        sa.Column("parent_signal_id", sa.String(length=128), nullable=False),
        sa.Column("parent_symbol", sa.String(length=32), nullable=False),
        sa.Column("parent_timeframe", sa.String(length=8), nullable=False),
        sa.Column("confirmed_time", sa.Integer(), nullable=False),
        sa.Column("candle_time", sa.Integer(), nullable=False),
        sa.Column("valid_until", sa.Integer(), nullable=False),
        sa.Column("frozen", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("state_time", sa.Integer(), nullable=False),
        sa.Column("lifecycle", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_execution_signals")),
    )
    with op.batch_alter_table("execution_signals", schema=None) as batch_op:
        batch_op.create_index(
            "ix_execution_signals_stream_time", ["symbol", "timeframe", "confirmed_time"]
        )
        batch_op.create_index("ix_execution_signals_parent", ["parent_signal_id"])


def downgrade() -> None:
    with op.batch_alter_table("execution_signals", schema=None) as batch_op:
        batch_op.drop_index("ix_execution_signals_parent")
        batch_op.drop_index("ix_execution_signals_stream_time")
    op.drop_table("execution_signals")
