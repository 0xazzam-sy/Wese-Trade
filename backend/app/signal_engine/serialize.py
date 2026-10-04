"""Signal/evaluation -> JSON payloads (API, WebSocket, persistence). Scores are /100
confluence values; no field is ever named or described as a probability."""

from __future__ import annotations

from typing import Any

from app.analysis.serialize import to_payload
from app.signal_engine.models import Hypothesis, Signal, SignalEvaluation, TradePlan


def plan_payload(plan: TradePlan | None) -> dict[str, Any] | None:
    if plan is None:
        return None
    payload = to_payload(plan)
    if not isinstance(payload, dict):  # pragma: no cover - a plan is a dataclass
        raise TypeError("plan did not serialize to an object")
    payload["rr"] = list(plan.rr())
    return payload


def hypothesis_payload(h: Hypothesis | None) -> dict[str, Any] | None:
    if h is None:
        return None
    return {
        "family": h.family.value,
        "side": h.side.value,
        "trigger": to_payload(h.trigger),
        "score": h.score,
        "base_score": h.base_score,
        "components": to_payload(h.components),
        "penalties": to_payload(h.penalties),
        "positive": list(h.positive),
        "negative": list(h.negative),
        "regime": h.regime,
    }


def evaluation_payload(ev: SignalEvaluation) -> dict[str, Any]:
    return {
        "symbol": ev.symbol,
        "timeframe": ev.timeframe,
        "candle_time": ev.candle_time,
        "developing": ev.developing,
        "signal_class": ev.signal_class.value,
        "side": ev.side.value if ev.side else None,
        "score": ev.score,
        "bull_score": ev.bull_score,
        "bear_score": ev.bear_score,
        "hypothesis": hypothesis_payload(ev.hypothesis),
        "plan": plan_payload(ev.plan) if ev.is_trade else None,
        "neutral_reason": ev.neutral_reason,
        "strategy_version": ev.strategy_version,
    }


def signal_payload(s: Signal) -> dict[str, Any]:
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
        "plan": plan_payload(s.plan),
        "components": to_payload(s.components),
        "penalties": to_payload(s.penalties),
        "positive": list(s.positive),
        "negative": list(s.negative),
        "evidence": to_payload(s.evidence),
        "strategy_version": s.strategy_version,
        "regime": s.regime,
        "state": s.state.value,
        "state_time": s.state_time,
        "entered_time": s.entered_time,
        "entry_price": s.entry_price,
        "targets_hit": s.targets_hit,
        "exit_reason": s.exit_reason.value if s.exit_reason else None,
        "closed_time": s.closed_time,
        "ambiguous": s.ambiguous,
        "gross_r": s.gross_r,
        "net_r": s.net_r,
        "history": [list(h) for h in s.history],
    }
