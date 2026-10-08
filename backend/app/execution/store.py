"""Execution-signal persistence (async SQLAlchemy). Frozen terms are written once; later
writes touch only the lifecycle columns."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.execution.codec import from_row, lifecycle, row_values
from app.execution.models import ExecutionSignal
from app.models.execution import ExecutionSignalRecord


async def save(session: AsyncSession, s: ExecutionSignal) -> None:
    row = await session.get(ExecutionSignalRecord, s.id)
    if row is None:
        session.add(ExecutionSignalRecord(**row_values(s)))
    else:  # lifecycle only: confirmed terms never change
        row.state = s.state.value
        row.state_time = s.state_time
        row.lifecycle = lifecycle(s)
    await session.commit()


async def stream_signals(
    session: AsyncSession, symbol: str, timeframe: str, limit: int = 50
) -> list[ExecutionSignal]:
    """Most recent execution signals of one stream, oldest first."""
    rows = (
        (
            await session.execute(
                select(ExecutionSignalRecord)
                .where(
                    ExecutionSignalRecord.symbol == symbol,
                    ExecutionSignalRecord.timeframe == timeframe,
                )
                .order_by(ExecutionSignalRecord.confirmed_time.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [from_row(r) for r in reversed(rows)]
