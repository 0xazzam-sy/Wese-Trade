"""Persistence of confirmed signals, their lifecycle/outcome, and backtest runs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.serialize import to_payload
from app.models.signal import BacktestRunRecord, SignalOutcomeRecord, SignalRecord
from app.signal_engine.models import Signal
from app.signal_engine.serialize import plan_payload


def _dt(seconds: int | None) -> datetime | None:
    return None if seconds is None else datetime.fromtimestamp(seconds, tz=UTC)


async def upsert_signal(session: AsyncSession, s: Signal, source: str = "live") -> None:
    record = await session.get(SignalRecord, s.id)
    if record is None:
        record = SignalRecord(
            id=s.id,
            source=source,
            symbol=s.symbol,
            timeframe=s.timeframe,
            side=s.side.value,
            signal_class=s.signal_class.value,
            family=s.family.value,
            score=s.score,
            strategy_version=s.strategy_version,
            trigger_id=s.trigger_id,
            trigger_at=_dt(s.trigger_time),
            confirmed_at=_dt(s.confirmed_time),
            plan=plan_payload(s.plan),
            components=to_payload(s.components),
            penalties=to_payload(s.penalties),
            reasons={"positive": list(s.positive), "negative": list(s.negative)},
            evidence=to_payload(s.evidence),
            state=s.state.value,
            state_at=_dt(s.state_time),
        )
        session.add(record)
        await session.flush()  # parent row first: signal_outcomes references it
    else:  # only the lifecycle moves; original fields are never rewritten
        record.state = s.state.value
        record.state_at = _dt(s.state_time) or record.state_at
    outcome = await session.get(SignalOutcomeRecord, s.id)
    if outcome is None:
        outcome = SignalOutcomeRecord(signal_id=s.id)
        session.add(outcome)
    outcome.entered_at = _dt(s.entered_time)
    outcome.entry_price = s.entry_price
    outcome.closed_at = _dt(s.closed_time)
    outcome.exit_reason = s.exit_reason.value if s.exit_reason else None
    outcome.targets_hit = s.targets_hit
    outcome.ambiguous = s.ambiguous
    outcome.gross_r = s.gross_r
    outcome.net_r = s.net_r
    outcome.mfe_r = s.mfe_r
    outcome.mae_r = s.mae_r
    outcome.bars_held = s.bars_held
    outcome.exits = [list(e) for e in s.exits]
    outcome.history = [list(h) for h in s.history]
    await session.commit()


async def recent_signal_ids(
    session: AsyncSession, symbol: str, timeframe: str, limit: int = 200
) -> set[str]:
    rows = await session.execute(
        select(SignalRecord.id)
        .where(SignalRecord.symbol == symbol, SignalRecord.timeframe == timeframe)
        .order_by(SignalRecord.confirmed_at.desc())
        .limit(limit)
    )
    return {r[0] for r in rows}


def record_payload(record: SignalRecord, outcome: SignalOutcomeRecord | None) -> dict[str, Any]:
    return {
        "id": record.id,
        "source": record.source,
        "symbol": record.symbol,
        "timeframe": record.timeframe,
        "side": record.side,
        "signal_class": record.signal_class,
        "family": record.family,
        "score": record.score,
        "strategy_version": record.strategy_version,
        "trigger_id": record.trigger_id,
        "trigger_time": int(record.trigger_at.timestamp()),
        "confirmed_time": int(record.confirmed_at.timestamp()),
        "plan": record.plan,
        "components": record.components,
        "penalties": record.penalties,
        "positive": record.reasons.get("positive", []),
        "negative": record.reasons.get("negative", []),
        "evidence": record.evidence,
        "state": record.state,
        "state_time": int(record.state_at.timestamp()),
        "outcome": None
        if outcome is None
        else {
            "entered_time": int(outcome.entered_at.timestamp()) if outcome.entered_at else None,
            "entry_price": outcome.entry_price,
            "closed_time": int(outcome.closed_at.timestamp()) if outcome.closed_at else None,
            "exit_reason": outcome.exit_reason,
            "targets_hit": outcome.targets_hit,
            "ambiguous": outcome.ambiguous,
            "gross_r": outcome.gross_r,
            "net_r": outcome.net_r,
            "history": outcome.history,
        },
    }


async def list_signals(
    session: AsyncSession, symbol: str, timeframe: str | None, limit: int
) -> list[dict[str, Any]]:
    query = select(SignalRecord, SignalOutcomeRecord).outerjoin(
        SignalOutcomeRecord, SignalOutcomeRecord.signal_id == SignalRecord.id
    )
    query = query.where(SignalRecord.symbol == symbol)
    if timeframe is not None:
        query = query.where(SignalRecord.timeframe == timeframe)
    rows = await session.execute(query.order_by(SignalRecord.confirmed_at.desc()).limit(limit))
    return [record_payload(r, o) for r, o in rows]


async def save_backtest_run(session: AsyncSession, name: str, report: dict[str, Any]) -> int:
    record = BacktestRunRecord(
        name=name,
        strategy_version=report["strategy_version"],
        config=to_payload(report["config"]),
        data=report["data"],
        summary={k: report[k] for k in ("all", "dev", "holdout")},
    )
    session.add(record)
    await session.commit()
    return record.id


async def list_backtest_runs(session: AsyncSession, limit: int = 20) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(BacktestRunRecord).order_by(BacktestRunRecord.created_at.desc()).limit(limit)
    )
    return [
        {
            "id": r.id,
            "name": r.name,
            "strategy_version": r.strategy_version,
            "created_at": r.created_at.isoformat(),
            "overall": r.summary.get("all", {}).get("overall"),
            "holdout": r.summary.get("holdout", {}).get("overall"),
        }
        for r in rows.scalars()
    ]


async def get_backtest_run(session: AsyncSession, run_id: int) -> dict[str, Any] | None:
    r = await session.get(BacktestRunRecord, run_id)
    if r is None:
        return None
    return {
        "id": r.id,
        "name": r.name,
        "strategy_version": r.strategy_version,
        "created_at": r.created_at.isoformat(),
        "config": r.config,
        "data": r.data,
        "summary": r.summary,
    }
