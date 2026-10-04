"""signals, signal outcomes and backtest runs

Revision ID: 0002_signals
Revises: 0001_create_users
Create Date: 2026-10-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_signals"
down_revision: str | None = "0001_create_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signals",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("signal_class", sa.String(length=16), nullable=False),
        sa.Column("family", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("strategy_version", sa.String(length=64), nullable=False),
        sa.Column("trigger_id", sa.String(length=128), nullable=False),
        sa.Column("trigger_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        sa.Column("components", sa.JSON(), nullable=False),
        sa.Column("penalties", sa.JSON(), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("state_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signals")),
    )
    op.create_index(
        "ix_signals_stream_time", "signals", ["symbol", "timeframe", "confirmed_at"], unique=False
    )
    op.create_table(
        "signal_outcomes",
        sa.Column("signal_id", sa.String(length=64), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_reason", sa.String(length=32), nullable=True),
        sa.Column("targets_hit", sa.Integer(), nullable=False),
        sa.Column("ambiguous", sa.Boolean(), nullable=False),
        sa.Column("gross_r", sa.Float(), nullable=True),
        sa.Column("net_r", sa.Float(), nullable=True),
        sa.Column("mfe_r", sa.Float(), nullable=False),
        sa.Column("mae_r", sa.Float(), nullable=False),
        sa.Column("bars_held", sa.Integer(), nullable=False),
        sa.Column("exits", sa.JSON(), nullable=False),
        sa.Column("history", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["signal_id"],
            ["signals.id"],
            name=op.f("fk_signal_outcomes_signal_id_signals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("signal_id", name=op.f("pk_signal_outcomes")),
    )
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backtest_runs")),
    )


def downgrade() -> None:
    op.drop_table("backtest_runs")
    op.drop_table("signal_outcomes")
    op.drop_index("ix_signals_stream_time", table_name="signals")
    op.drop_table("signals")
