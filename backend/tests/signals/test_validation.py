"""Strategy validation status: transitions, research-only timeframes, frozen baseline."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.signal_engine.config import DEFAULT_SIGNAL_CONFIG, strategy_version
from app.signal_engine.enums import Side, SignalClass
from app.signal_engine.models import SignalEvaluation
from app.signal_engine.validation import (
    PHASE4_BASELINE,
    RESEARCH_ONLY_REASON,
    STATUS_AR,
    InvalidTransitionError,
    ValidationStatus,
    transition,
)

S = ValidationStatus


def _ev(timeframe: str, cls: SignalClass = SignalClass.BUY) -> SignalEvaluation:
    return SignalEvaluation(
        "BTCUSDT",
        timeframe,
        0,
        False,
        cls,
        Side.LONG if cls is not SignalClass.NEUTRAL else None,
        80.0,
        80.0,
        10.0,
        None,
        None,
        None,
        None,
        None,
        "v",
    )


def test_baseline_version_is_frozen() -> None:
    # Phase 4.1 must never silently change the Phase 4 baseline.
    assert strategy_version(DEFAULT_SIGNAL_CONFIG) == "wese-trade-signal-4.0-f26f636443"
    assert PHASE4_BASELINE.version == "wese-trade-signal-4.0-f26f636443"
    assert PHASE4_BASELINE.status is S.UNPROVEN
    assert STATUS_AR[PHASE4_BASELINE.status] == "غير مُثبت"
    assert PHASE4_BASELINE.label_ar == "تجريبي"


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (S.UNPROVEN, S.TESTING),
        (S.TESTING, S.PASSED_HISTORICAL),
        (S.TESTING, S.REJECTED),
        (S.PASSED_HISTORICAL, S.FORWARD_TEST),
        (S.PASSED_HISTORICAL, S.REJECTED),
        (S.FORWARD_TEST, S.REJECTED),
        (S.REJECTED, S.TESTING),
    ],
)
def test_allowed_transitions(a: S, b: S) -> None:
    assert transition(a, b) is b


@pytest.mark.parametrize(
    ("a", "b"),
    [
        (S.UNPROVEN, S.FORWARD_TEST),  # never skip historical validation
        (S.UNPROVEN, S.PASSED_HISTORICAL),
        (S.TESTING, S.FORWARD_TEST),
        (S.REJECTED, S.FORWARD_TEST),
        (S.FORWARD_TEST, S.PASSED_HISTORICAL),
    ],
)
def test_forbidden_transitions(a: S, b: S) -> None:
    with pytest.raises(InvalidTransitionError):
        transition(a, b)


def test_research_only_timeframes_never_emit_directional_signals() -> None:
    for tf in ("1m", "5m", "10m"):
        out = PHASE4_BASELINE.apply(_ev(tf))
        assert out.signal_class is SignalClass.NEUTRAL and out.side is None
        assert out.neutral_reason == RESEARCH_ONLY_REASON
    for tf in ("15m", "30m", "1h"):
        assert PHASE4_BASELINE.apply(_ev(tf)).signal_class is SignalClass.BUY
    neutral = _ev("1m", SignalClass.NEUTRAL)
    assert PHASE4_BASELINE.apply(neutral) is neutral


def test_rejected_strategy_has_no_signal_timeframes_and_forward_test_flag() -> None:
    rejected = replace(PHASE4_BASELINE, status=S.REJECTED)
    assert not any(rejected.signal_capable(tf) for tf in ("15m", "30m", "1h"))
    forward = replace(PHASE4_BASELINE, status=S.FORWARD_TEST)
    info = forward.info("1h")
    assert info["forward_test"] is True and info["status_ar"] == "اختبار مباشر"
    assert PHASE4_BASELINE.info("1h")["forward_test"] is False
