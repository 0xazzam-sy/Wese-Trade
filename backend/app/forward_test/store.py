"""Forward-test persistence (async SQLAlchemy). Frozen signal terms are written ONCE;
later writes touch only lifecycle columns. One open run per strategy version."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.forward_test.codec import freeze, lifecycle, thaw
from app.forward_test.metrics import cost_breakdown
from app.models.forward_test import (
    ForwardTestCheckpoint,
    ForwardTestCursor,
    ForwardTestOutcome,
    ForwardTestRun,
    ForwardTestSignal,
)
from app.signal_engine.config import SignalConfig
from app.signal_engine.models import Signal

ACTIVE_STATUSES = ("forward_testing", "paused")
STATUSES = ("forward_testing", "paused", "stopped", "passed_forward_test", "failed_forward_test")
TRANSITIONS: dict[str, frozenset[str]] = {
    "forward_testing": frozenset(
        {"paused", "stopped", "passed_forward_test", "failed_forward_test"}
    ),
    "paused": frozenset({"forward_testing", "stopped", "failed_forward_test"}),
    "stopped": frozenset(),
    "passed_forward_test": frozenset(),
    "failed_forward_test": frozenset(),
}


class RunConflictError(RuntimeError):
    pass


class InvalidRunTransitionError(ValueError):
    pass


def ts(seconds: int | None) -> datetime | None:
    return None if seconds is None else datetime.fromtimestamp(seconds, tz=UTC)


async def open_run(session: AsyncSession, version: str | None = None) -> ForwardTestRun | None:
    query = select(ForwardTestRun).where(ForwardTestRun.stopped_at.is_(None))
    if version is not None:
        query = query.where(ForwardTestRun.strategy_version == version)
    return (await session.execute(query.order_by(ForwardTestRun.id.desc()))).scalars().first()


async def create_run(
    session: AsyncSession,
    *,
    version: str,
    fingerprint: str,
    research_version: str,
    config: dict[str, Any],
    started_at: datetime,
    symbols: list[str],
    timeframes: list[str],
    cost_model: dict[str, Any],
    minimum_required_trades: int,
    minimum_days: int,
    notes: str = "",
) -> ForwardTestRun:
    if await open_run(session, version) is not None:
        raise RunConflictError(f"an open forward-test run already exists for {version}")
    run = ForwardTestRun(
        strategy_version=version,
        fingerprint=fingerprint,
        research_version=research_version,
        config=config,
        started_at=started_at,
        status="forward_testing",
        symbols=symbols,
        timeframes=timeframes,
        cost_model=cost_model,
        minimum_required_trades=minimum_required_trades,
        minimum_days=minimum_days,
        notes=notes,
        status_history=[[started_at.isoformat(), "forward_testing", "run started"]],
    )
    session.add(run)
    await session.commit()
    return run


async def set_status(
    session: AsyncSession, run_id: int, status: str, note: str, now: datetime
) -> ForwardTestRun:
    run = await session.get(ForwardTestRun, run_id)
    if run is None:
        raise LookupError("forward_test_run_not_found")
    if status not in TRANSITIONS[run.status]:
        raise InvalidRunTransitionError(f"{run.status} -> {status} is not allowed")
    run.status = status
    run.status_history = [*run.status_history, [now.isoformat(), status, note]]
    if status not in ACTIVE_STATUSES:
        run.stopped_at = now
    await session.commit()
    return run


async def save_signal(
    session: AsyncSession, run_id: int, signal: Signal, cfg: SignalConfig
) -> None:
    """Insert on first sight (frozen terms), then update ONLY lifecycle columns."""
    row = (
        await session.execute(
            select(ForwardTestSignal).where(
                ForwardTestSignal.run_id == run_id, ForwardTestSignal.signal_id == signal.id
            )
        )
    ).scalar_one_or_none()
    life = lifecycle(signal)
    if row is None:
        plan = signal.plan
        row = ForwardTestSignal(
            run_id=run_id,
            signal_id=signal.id,
            strategy_version=signal.strategy_version,
            symbol=signal.symbol,
            timeframe=signal.timeframe,
            side=signal.side.value,
            signal_class=signal.signal_class.value,
            family=signal.family.value,
            score=signal.score,
            regime=signal.regime,
            confirmed_at=ts(signal.confirmed_time),
            entry_model=plan.entry_model.value,
            entry=plan.preferred_entry,
            stop=plan.stop,
            tp1=plan.targets[0].price,
            tp2=plan.targets[1].price,
            tp3=plan.targets[2].price,
            frozen=freeze(signal),
            state=signal.state.value,
            state_at=ts(signal.state_time),
            lifecycle=life,
        )
        session.add(row)
        await session.flush()
    row.state = signal.state.value
    row.state_at = ts(signal.state_time) or row.state_at
    row.entered_at = ts(signal.entered_time)
    row.entry_price = signal.entry_price
    row.closed_at = ts(signal.closed_time)
    row.lifecycle = life
    if signal.state.is_final and await session.get(ForwardTestOutcome, row.id) is None:
        fees, slip = cost_breakdown(signal, cfg)
        session.add(
            ForwardTestOutcome(
                signal_pk=row.id,
                run_id=run_id,
                outcome=signal.state.value,
                exit_reason=signal.exit_reason.value if signal.exit_reason else None,
                entered=signal.entered,
                gross_r=signal.gross_r,
                net_r=signal.net_r,
                fees_r=fees,
                slippage_r=slip,
                holding_bars=signal.bars_held,
                targets_hit=signal.targets_hit,
                ambiguous=signal.ambiguous,
                closed_at=ts(signal.closed_time or signal.state_time),
            )
        )
    await session.commit()


async def load_signals(session: AsyncSession, run_id: int) -> list[Signal]:
    rows = (
        await session.execute(
            select(ForwardTestSignal)
            .where(ForwardTestSignal.run_id == run_id)
            .order_by(ForwardTestSignal.confirmed_at, ForwardTestSignal.id)
        )
    ).scalars()
    return [thaw(r.frozen, r.lifecycle) for r in rows]


async def cursors(session: AsyncSession, run_id: int) -> dict[tuple[str, str], int]:
    rows = (
        await session.execute(select(ForwardTestCursor).where(ForwardTestCursor.run_id == run_id))
    ).scalars()
    return {(r.symbol, r.timeframe): r.last_close_time for r in rows}


async def save_cursors(
    session: AsyncSession, run_id: int, values: dict[tuple[str, str], int]
) -> None:
    for (symbol, tf), close in values.items():
        row = await session.get(ForwardTestCursor, (run_id, symbol, tf))
        if row is None:
            session.add(
                ForwardTestCursor(run_id=run_id, symbol=symbol, timeframe=tf, last_close_time=close)
            )
        elif close > row.last_close_time:
            row.last_close_time = close
    await session.commit()


async def save_checkpoint(
    session: AsyncSession, run_id: int, day: date, metrics: dict[str, Any]
) -> bool:
    exists = (
        await session.execute(
            select(ForwardTestCheckpoint).where(
                ForwardTestCheckpoint.run_id == run_id, ForwardTestCheckpoint.day == day
            )
        )
    ).scalar_one_or_none()
    if exists is not None:
        return False
    session.add(ForwardTestCheckpoint(run_id=run_id, day=day, metrics=metrics))
    await session.commit()
    return True


async def checkpoints(session: AsyncSession, run_id: int) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(ForwardTestCheckpoint)
            .where(ForwardTestCheckpoint.run_id == run_id)
            .order_by(ForwardTestCheckpoint.day)
        )
    ).scalars()
    return [{"day": r.day.isoformat(), "metrics": r.metrics} for r in rows]


async def outcomes(session: AsyncSession, run_id: int) -> dict[int, ForwardTestOutcome]:
    rows = (
        await session.execute(select(ForwardTestOutcome).where(ForwardTestOutcome.run_id == run_id))
    ).scalars()
    return {r.signal_pk: r for r in rows}


async def signal_rows(
    session: AsyncSession,
    run_id: int,
    *,
    symbol: str | None = None,
    timeframe: str | None = None,
    side: str | None = None,
    state: str | None = None,
    limit: int | None = 200,
) -> list[ForwardTestSignal]:
    query = select(ForwardTestSignal).where(ForwardTestSignal.run_id == run_id)
    if symbol:
        query = query.where(ForwardTestSignal.symbol == symbol)
    if timeframe:
        query = query.where(ForwardTestSignal.timeframe == timeframe)
    if side:
        query = query.where(ForwardTestSignal.side == side)
    if state:
        query = query.where(ForwardTestSignal.state == state)
    query = query.order_by(ForwardTestSignal.confirmed_at.desc(), ForwardTestSignal.id.desc())
    if limit:
        query = query.limit(limit)
    return list((await session.execute(query)).scalars())


def run_payload(run: ForwardTestRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "strategy_version": run.strategy_version,
        "fingerprint": run.fingerprint,
        "research_version": run.research_version,
        "started_at": run.started_at.isoformat(),
        "stopped_at": run.stopped_at.isoformat() if run.stopped_at else None,
        "status": run.status,
        "symbols": run.symbols,
        "timeframes": run.timeframes,
        "cost_model": run.cost_model,
        "minimum_required_trades": run.minimum_required_trades,
        "minimum_days": run.minimum_days,
        "notes": run.notes,
        "status_history": run.status_history,
        "created_at": run.created_at.isoformat(),
    }


def signal_row_payload(r: ForwardTestSignal, outcome: ForwardTestOutcome | None) -> dict[str, Any]:
    life = r.lifecycle
    return {
        "signal_id": r.signal_id,
        "strategy_version": r.strategy_version,
        "symbol": r.symbol,
        "timeframe": r.timeframe,
        "side": r.side,
        "family": r.family,
        "score": r.score,
        "regime": r.regime,
        "confirmed_at": r.confirmed_at.isoformat(),
        "entry_model": r.entry_model,
        "entry": r.entry,
        "stop": r.stop,
        "tp1": r.tp1,
        "tp2": r.tp2,
        "tp3": r.tp3,
        "state": r.state,
        "entered_at": r.entered_at.isoformat() if r.entered_at else None,
        "entry_price": r.entry_price,
        "closed_at": r.closed_at.isoformat() if r.closed_at else None,
        "targets_hit": life.get("targets_hit", 0),
        "ambiguous": life.get("ambiguous", False),
        "holding_bars": life.get("bars_held", 0),
        "gross_r": life.get("gross_r"),
        "net_r": life.get("net_r"),
        "fees_r": outcome.fees_r if outcome else None,
        "slippage_r": outcome.slippage_r if outcome else None,
        "exit_reason": life.get("exit_reason"),
        "positive": r.frozen.get("positive", []),
        "negative": r.frozen.get("negative", []),
    }
