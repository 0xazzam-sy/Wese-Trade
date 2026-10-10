"""Strategy 4.3 persistence: canonical signals (frozen terms + lifecycle) and stream cursors."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.forward_test.codec import freeze, lifecycle, thaw
from app.models.strategy43 import Strategy43CursorRecord, Strategy43SignalRecord
from app.signal_engine.enums import SignalState
from app.signal_engine.models import Signal
from app.strategy43.config import tier

OPEN_STATES = tuple(
    s.value
    for s in (SignalState.CONFIRMED, SignalState.ACTIVE, SignalState.TP1_HIT, SignalState.TP2_HIT)
)


async def save_signal(session: AsyncSession, signal: Signal, valid_until: int) -> None:
    """Insert on first sight (frozen terms), then update ONLY lifecycle columns."""
    row = await session.get(Strategy43SignalRecord, signal.id)
    life = lifecycle(signal)
    if row is None:
        session.add(
            Strategy43SignalRecord(
                id=signal.id,
                symbol=signal.symbol,
                timeframe=signal.timeframe,
                side=1 if signal.side.value == "long" else -1,
                tier=tier(signal.score),
                score=signal.score,
                family=signal.family.value,
                strategy_version=signal.strategy_version,
                candle_time=signal.trigger_time,
                confirmed_time=signal.confirmed_time,
                valid_until=valid_until,
                frozen=freeze(signal),
                state=signal.state.value,
                state_time=signal.state_time,
                lifecycle=life,
            )
        )
    else:
        row.state = signal.state.value
        row.state_time = signal.state_time
        row.lifecycle = life
    await session.commit()


async def open_signals(session: AsyncSession, version: str) -> list[Signal]:
    rows = (
        (
            await session.execute(
                select(Strategy43SignalRecord)
                .where(
                    Strategy43SignalRecord.state.in_(OPEN_STATES),
                    Strategy43SignalRecord.strategy_version == version,
                )
                .order_by(Strategy43SignalRecord.confirmed_time)
            )
        )
        .scalars()
        .all()
    )
    return [thaw(r.frozen, r.lifecycle) for r in rows]


async def recent_signals(
    session: AsyncSession, symbol: str | None = None, timeframe: str | None = None, limit: int = 50
) -> list[Signal]:
    q = select(Strategy43SignalRecord)
    if symbol:
        q = q.where(Strategy43SignalRecord.symbol == symbol)
    if timeframe:
        q = q.where(Strategy43SignalRecord.timeframe == timeframe)
    rows = (
        (
            await session.execute(
                q.order_by(Strategy43SignalRecord.confirmed_time.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [thaw(r.frozen, r.lifecycle) for r in reversed(rows)]


async def counts_since(session: AsyncSession, since: int) -> dict[str, Any]:
    rows = (
        await session.execute(
            select(Strategy43SignalRecord.tier, func.count())
            .where(Strategy43SignalRecord.confirmed_time >= since)
            .group_by(Strategy43SignalRecord.tier)
        )
    ).all()
    by_tier = {str(t): int(n) for t, n in rows}
    return {"total": sum(by_tier.values()), "by_tier": by_tier}


async def last_signal_time(session: AsyncSession) -> int | None:
    value = (
        await session.execute(select(func.max(Strategy43SignalRecord.confirmed_time)))
    ).scalar()
    return int(value) if value is not None else None


async def cursors(session: AsyncSession) -> dict[tuple[str, str], int]:
    rows = (await session.execute(select(Strategy43CursorRecord))).scalars().all()
    return {(r.symbol, r.timeframe): r.close_time for r in rows}


async def save_cursors(session: AsyncSession, values: dict[tuple[str, str], int]) -> None:
    for (symbol, tf), close in values.items():
        row = await session.get(Strategy43CursorRecord, (symbol, tf))
        if row is None:
            session.add(Strategy43CursorRecord(symbol=symbol, timeframe=tf, close_time=close))
        elif close > row.close_time:
            row.close_time = close
    await session.commit()
