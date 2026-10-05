"""Exact freeze/thaw of a forward-test `Signal` (restart restoration and audit).

`freeze` captures the original terms at confirmation (never updated afterwards);
`lifecycle` captures the forward-only lifecycle state. `thaw(freeze(s), lifecycle(s))`
reconstructs an equivalent `Signal`, so open signals resume exactly after a restart.
"""

from __future__ import annotations

from typing import Any

from app.signal_engine.enums import (
    EntryModel,
    ExitReason,
    SetupFamily,
    Side,
    SignalClass,
    SignalState,
)
from app.signal_engine.models import Component, Penalty, Signal, Target, TradePlan


def freeze(s: Signal) -> dict[str, Any]:
    p = s.plan
    return {
        "id": s.id,
        "symbol": s.symbol,
        "timeframe": s.timeframe,
        "side": s.side.value,
        "signal_class": s.signal_class.value,
        "family": s.family.value,
        "score": s.score,
        "trigger_id": s.trigger_id,
        "trigger_time": s.trigger_time,
        "confirmed_time": s.confirmed_time,
        "plan": {
            "entry_model": p.entry_model.value,
            "entry_low": p.entry_low,
            "entry_high": p.entry_high,
            "preferred_entry": p.preferred_entry,
            "stop": p.stop,
            "invalidation": p.invalidation,
            "stop_source": p.stop_source,
            "risk": p.risk,
            "risk_atr": p.risk_atr,
            "targets": [[t.price, t.rr, t.source] for t in p.targets],
        },
        "components": [[c.name, c.value, c.weight, c.points] for c in s.components],
        "penalties": [[x.code, x.points, x.reason] for x in s.penalties],
        "positive": list(s.positive),
        "negative": list(s.negative),
        "evidence": s.evidence,
        "strategy_version": s.strategy_version,
        "regime": s.regime,
    }


def lifecycle(s: Signal) -> dict[str, Any]:
    return {
        "state": s.state.value,
        "state_time": s.state_time,
        "entered_time": s.entered_time,
        "entry_price": s.entry_price,
        "remaining": s.remaining,
        "targets_hit": s.targets_hit,
        "exits": [list(e) for e in s.exits],
        "exit_reason": s.exit_reason.value if s.exit_reason else None,
        "closed_time": s.closed_time,
        "ambiguous": s.ambiguous,
        "bars_held": s.bars_held,
        "bars_pending": s.bars_pending,
        "gross_r": s.gross_r,
        "net_r": s.net_r,
        "mfe_r": s.mfe_r,
        "mae_r": s.mae_r,
        "history": [list(h) for h in s.history],
        "evidence": s.evidence,  # carries the tracker's entry_market flag
    }


def thaw(frozen: dict[str, Any], life: dict[str, Any]) -> Signal:
    p = frozen["plan"]
    t1, t2, t3 = (Target(price, rr, source) for price, rr, source in p["targets"])
    plan = TradePlan(
        entry_model=EntryModel(p["entry_model"]),
        entry_low=p["entry_low"],
        entry_high=p["entry_high"],
        preferred_entry=p["preferred_entry"],
        stop=p["stop"],
        invalidation=p["invalidation"],
        stop_source=p["stop_source"],
        risk=p["risk"],
        risk_atr=p["risk_atr"],
        targets=(t1, t2, t3),
    )
    return Signal(
        id=frozen["id"],
        symbol=frozen["symbol"],
        timeframe=frozen["timeframe"],
        side=Side(frozen["side"]),
        signal_class=SignalClass(frozen["signal_class"]),
        family=SetupFamily(frozen["family"]),
        score=frozen["score"],
        trigger_id=frozen["trigger_id"],
        trigger_time=frozen["trigger_time"],
        confirmed_time=frozen["confirmed_time"],
        plan=plan,
        components=tuple(Component(*c) for c in frozen["components"]),
        penalties=tuple(Penalty(*x) for x in frozen["penalties"]),
        positive=tuple(frozen["positive"]),
        negative=tuple(frozen["negative"]),
        evidence=life.get("evidence", frozen["evidence"]),
        strategy_version=frozen["strategy_version"],
        regime=frozen["regime"],
        state=SignalState(life["state"]),
        state_time=life["state_time"],
        entered_time=life["entered_time"],
        entry_price=life["entry_price"],
        remaining=life["remaining"],
        targets_hit=life["targets_hit"],
        exits=[(f, price, why) for f, price, why in life["exits"]],
        exit_reason=ExitReason(life["exit_reason"]) if life["exit_reason"] else None,
        closed_time=life["closed_time"],
        ambiguous=life["ambiguous"],
        bars_held=life["bars_held"],
        bars_pending=life["bars_pending"],
        gross_r=life["gross_r"],
        net_r=life["net_r"],
        mfe_r=life["mfe_r"],
        mae_r=life["mae_r"],
        history=[(t, st) for t, st in life["history"]],
    )
