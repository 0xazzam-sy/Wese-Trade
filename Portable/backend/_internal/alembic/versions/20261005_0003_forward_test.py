"""forward-test runs, signals, outcomes, cursors and checkpoints (Phase 4.2)

Revision ID: 0003_forward_test
Revises: 0002_signals
Create Date: 2026-10-05
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_forward_test"
down_revision: str | None = "0002_signals"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "forward_test_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("strategy_version", sa.String(length=64), nullable=False),
        sa.Column("fingerprint", sa.String(length=32), nullable=False),
        sa.Column("research_version", sa.String(length=64), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=False),
        sa.Column("timeframes", sa.JSON(), nullable=False),
        sa.Column("cost_model", sa.JSON(), nullable=False),
        sa.Column("minimum_required_trades", sa.Integer(), nullable=False),
        sa.Column("minimum_days", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("status_history", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forward_test_runs")),
    )
    with op.batch_alter_table("forward_test_runs", schema=None) as batch_op:
        batch_op.create_index(
            "uq_forward_test_runs_open_version",
            ["strategy_version"],
            unique=True,
            sqlite_where=sa.text("stopped_at IS NULL"),
            postgresql_where=sa.text("stopped_at IS NULL"),
        )

    op.create_table(
        "forward_test_checkpoints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["forward_test_runs.id"],
            name=op.f("fk_forward_test_checkpoints_run_id_forward_test_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forward_test_checkpoints")),
    )
    with op.batch_alter_table("forward_test_checkpoints", schema=None) as batch_op:
        batch_op.create_index("uq_forward_test_checkpoint_day", ["run_id", "day"], unique=True)

    op.create_table(
        "forward_test_cursors",
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("last_close_time", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["forward_test_runs.id"],
            name=op.f("fk_forward_test_cursors_run_id_forward_test_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "run_id", "symbol", "timeframe", name=op.f("pk_forward_test_cursors")
        ),
    )
    op.create_table(
        "forward_test_signals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("signal_id", sa.String(length=64), nullable=False),
        sa.Column("strategy_version", sa.String(length=64), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("side", sa.String(length=8), nullable=False),
        sa.Column("signal_class", sa.String(length=16), nullable=False),
        sa.Column("family", sa.String(length=32), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("regime", sa.String(length=32), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_model", sa.String(length=16), nullable=False),
        sa.Column("entry", sa.Float(), nullable=False),
        sa.Column("stop", sa.Float(), nullable=False),
        sa.Column("tp1", sa.Float(), nullable=False),
        sa.Column("tp2", sa.Float(), nullable=False),
        sa.Column("tp3", sa.Float(), nullable=False),
        sa.Column("frozen", sa.JSON(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("state_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lifecycle", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["forward_test_runs.id"],
            name=op.f("fk_forward_test_signals_run_id_forward_test_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_forward_test_signals")),
    )
    with op.batch_alter_table("forward_test_signals", schema=None) as batch_op:
        batch_op.create_index(
            "ix_forward_test_signals_stream",
            ["run_id", "symbol", "timeframe", "confirmed_at"],
            unique=False,
        )
        batch_op.create_index("uq_forward_test_signal", ["run_id", "signal_id"], unique=True)

    op.create_table(
        "forward_test_outcomes",
        sa.Column("signal_pk", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("exit_reason", sa.String(length=32), nullable=True),
        sa.Column("entered", sa.Boolean(), nullable=False),
        sa.Column("gross_r", sa.Float(), nullable=True),
        sa.Column("net_r", sa.Float(), nullable=True),
        sa.Column("fees_r", sa.Float(), nullable=True),
        sa.Column("slippage_r", sa.Float(), nullable=True),
        sa.Column("holding_bars", sa.Integer(), nullable=False),
        sa.Column("targets_hit", sa.Integer(), nullable=False),
        sa.Column("ambiguous", sa.Boolean(), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["forward_test_runs.id"],
            name=op.f("fk_forward_test_outcomes_run_id_forward_test_runs"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["signal_pk"],
            ["forward_test_signals.id"],
            name=op.f("fk_forward_test_outcomes_signal_pk_forward_test_signals"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("signal_pk", name=op.f("pk_forward_test_outcomes")),
    )


def downgrade() -> None:
    op.drop_table("forward_test_outcomes")
    with op.batch_alter_table("forward_test_signals", schema=None) as batch_op:
        batch_op.drop_index("uq_forward_test_signal")
        batch_op.drop_index("ix_forward_test_signals_stream")

    op.drop_table("forward_test_signals")
    op.drop_table("forward_test_cursors")
    with op.batch_alter_table("forward_test_checkpoints", schema=None) as batch_op:
        batch_op.drop_index("uq_forward_test_checkpoint_day")

    op.drop_table("forward_test_checkpoints")
    with op.batch_alter_table("forward_test_runs", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_forward_test_runs_open_version",
            sqlite_where=sa.text("stopped_at IS NULL"),
            postgresql_where=sa.text("stopped_at IS NULL"),
        )

    op.drop_table("forward_test_runs")
