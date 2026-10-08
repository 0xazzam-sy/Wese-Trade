"""Execution signal <-> persisted row, and UI payloads (`execution.update`)."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.execution.engine import score_band
from app.execution.models import (
    DECISION_AR,
    EXECUTION_VERSION,
    STATE_AR,
    Evaluation,
    ExecState,
    ExecutionSignal,
    Micro,
    ParentSetup,
    Plan,
)


def plan_payload(p: Plan) -> dict[str, Any]:
    return {
        "side": p.side,
        "entry": p.entry,
        "parent_entry": p.parent_entry,
        "stop": p.stop,
        "parent_stop": p.parent_stop,
        "stop_source": p.stop_source,
        "targets": list(p.targets),
        "target_sources": list(p.target_sources),
        "rr": list(p.rr),
    }


def plan_from(d: dict[str, Any]) -> Plan:
    return Plan(
        side=int(d["side"]),
        entry=float(d["entry"]),
        parent_entry=float(d["parent_entry"]),
        stop=float(d["stop"]),
        parent_stop=float(d["parent_stop"]),
        stop_source=str(d["stop_source"]),
        targets=tuple(float(x) for x in d["targets"]),  # type: ignore[arg-type]
        target_sources=tuple(str(x) for x in d["target_sources"]),  # type: ignore[arg-type]
    )


def parent_payload(p: ParentSetup) -> dict[str, Any]:
    out = asdict(p)
    out["targets"] = list(p.targets)
    out["fingerprint"] = f"4.2-{p.strategy_version.rsplit('-', 1)[-1][:7]}"
    return out


def parent_from(d: dict[str, Any]) -> ParentSetup:
    keys = ParentSetup.__dataclass_fields__
    data = {k: v for k, v in d.items() if k in keys}
    data["targets"] = tuple(float(x) for x in d["targets"])
    return ParentSetup(**data)


def micro_payload(m: Micro | None) -> dict[str, Any] | None:
    if m is None:
        return None
    return {
        "status": m.status,
        "spread_bp": m.spread_bp,
        "spread_normal_bp": m.spread_normal_bp,
        "book_imbalance": m.book_imbalance,
        "flow_imbalance": m.flow_imbalance,
        "book_age_s": m.book_age_s,
        "trade_age_s": m.trade_age_s,
        "reasons": list(m.reasons),
    }


# --- persistence ---------------------------------------------------------------------------
def frozen(s: ExecutionSignal) -> dict[str, Any]:
    return {
        "plan": plan_payload(s.plan),
        "parent": parent_payload(s.parent),
        "reasons": list(s.reasons),
        "trigger": s.trigger,
        "micro": s.micro,
    }


def lifecycle(s: ExecutionSignal) -> dict[str, Any]:
    return {
        "entered_time": s.entered_time,
        "targets_hit": s.targets_hit,
        "closed_time": s.closed_time,
        "bars": s.bars,
        "cursor": s.cursor,
        "history": [list(h) for h in s.history],
    }


def row_values(s: ExecutionSignal) -> dict[str, Any]:
    return {
        "id": s.id,
        "symbol": s.symbol,
        "timeframe": s.timeframe,
        "side": s.side,
        "score": s.score,
        "execution_version": s.execution_version,
        "parent_strategy": s.parent.strategy,
        "parent_strategy_version": s.parent.strategy_version,
        "parent_signal_id": s.parent.signal_id,
        "parent_symbol": s.parent.symbol,
        "parent_timeframe": s.parent.timeframe,
        "confirmed_time": s.confirmed_time,
        "candle_time": s.candle_time,
        "valid_until": s.valid_until,
        "frozen": frozen(s),
        "state": s.state.value,
        "state_time": s.state_time,
        "lifecycle": lifecycle(s),
    }


def from_row(row: Any) -> ExecutionSignal:
    fz, lc = row.frozen, row.lifecycle
    return ExecutionSignal(
        id=row.id,
        symbol=row.symbol,
        timeframe=row.timeframe,
        side=int(row.side),
        score=float(row.score),
        confirmed_time=int(row.confirmed_time),
        candle_time=int(row.candle_time),
        valid_until=int(row.valid_until),
        plan=plan_from(fz["plan"]),
        parent=parent_from(fz["parent"]),
        reasons=tuple(fz.get("reasons", ())),
        trigger=str(fz.get("trigger") or ""),
        execution_version=row.execution_version or EXECUTION_VERSION,
        micro=fz.get("micro"),
        state=ExecState(row.state),
        state_time=int(row.state_time),
        entered_time=lc.get("entered_time"),
        targets_hit=int(lc.get("targets_hit", 0)),
        closed_time=lc.get("closed_time"),
        bars=int(lc.get("bars", 0)),
        cursor=int(lc.get("cursor", row.confirmed_time)),
        history=[(int(t), str(st)) for t, st in lc.get("history", [])],
    )


# --- UI ------------------------------------------------------------------------------------
def signal_payload(s: ExecutionSignal) -> dict[str, Any]:
    return {
        "id": s.id,
        "symbol": s.symbol,
        "timeframe": s.timeframe,
        "side": s.side,
        "score": s.score,
        "confirmed_time": s.confirmed_time,
        "candle_time": s.candle_time,
        "valid_until": s.valid_until,
        "plan": plan_payload(s.plan),
        "parent": parent_payload(s.parent),
        "reasons": list(s.reasons),
        "trigger": s.trigger,
        "state": s.state.value,
        "state_ar": STATE_AR[s.state],
        "state_time": s.state_time,
        "entered_time": s.entered_time,
        "targets_hit": s.targets_hit,
        "closed_time": s.closed_time,
        "execution_version": s.execution_version,
        "history": [list(h) for h in s.history],
    }


def marker_payload(s: ExecutionSignal) -> dict[str, Any]:
    return {"id": s.id, "time": s.candle_time, "side": s.side, "state": s.state.value}


def evaluation_payload(ev: Evaluation) -> dict[str, Any]:
    return {
        "candle_time": ev.candle_time,
        "decision": ev.decision.value,
        "decision_ar": DECISION_AR[ev.decision],
        "score": ev.score,
        "score_band": score_band(ev.score) if ev.parent is not None else None,
        "side": ev.side,
        "headline": ev.headline,
        "reasons": list(ev.reasons),
        "cautions": list(ev.cautions),
        "components": {k: round(v, 3) for k, v in ev.components.items()},
        "parent": parent_payload(ev.parent) if ev.parent is not None else None,
        "plan": plan_payload(ev.plan) if ev.plan is not None else None,
        "trigger": ev.trigger,
        "micro": micro_payload(ev.micro),
    }
