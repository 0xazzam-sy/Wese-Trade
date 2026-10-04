"""Strategy validation status and deployment policy (Phase 4.1).

A strategy version is never "trusted" by default. Its status moves through an explicit
state machine, decided by documented research (docs/research.md), never automatically:

    UNPROVEN --> TESTING --> PASSED_HISTORICAL --> FORWARD_TEST
                    |               |                   |
                    +--> REJECTED <-+-------------------+
    REJECTED --> TESTING   (only a NEW version can be re-tested; history is kept)

The deployment policy says on which timeframes a version may emit DIRECTIONAL live
signals. On every other timeframe the engine still evaluates (fully transparent), but a
BUY/SELL is shown as NEUTRAL with the reason "research only". Signals are analytical in
every status, including FORWARD_TEST («اختبار مباشر»).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Any

from app.signal_engine.config import DEFAULT_SIGNAL_CONFIG, strategy_version
from app.signal_engine.enums import SignalClass
from app.signal_engine.models import SignalEvaluation


class ValidationStatus(StrEnum):
    UNPROVEN = "unproven"
    TESTING = "testing"
    PASSED_HISTORICAL = "passed_historical"
    FORWARD_TEST = "forward_test"
    REJECTED = "rejected"


STATUS_AR: dict[ValidationStatus, str] = {
    ValidationStatus.UNPROVEN: "غير مُثبت",
    ValidationStatus.TESTING: "قيد الاختبار",
    ValidationStatus.PASSED_HISTORICAL: "اجتاز الاختبار التاريخي",
    ValidationStatus.FORWARD_TEST: "اختبار مباشر",
    ValidationStatus.REJECTED: "مرفوض",
}

TRANSITIONS: dict[ValidationStatus, frozenset[ValidationStatus]] = {
    ValidationStatus.UNPROVEN: frozenset({ValidationStatus.TESTING}),
    ValidationStatus.TESTING: frozenset(
        {ValidationStatus.PASSED_HISTORICAL, ValidationStatus.REJECTED}
    ),
    ValidationStatus.PASSED_HISTORICAL: frozenset(
        {ValidationStatus.FORWARD_TEST, ValidationStatus.REJECTED}
    ),
    ValidationStatus.FORWARD_TEST: frozenset({ValidationStatus.REJECTED}),
    ValidationStatus.REJECTED: frozenset({ValidationStatus.TESTING}),
}

RESEARCH_ONLY_REASON = "إطار زمني للبحث فقط — لا إشارات اتجاهية لهذا الإطار"


class InvalidTransitionError(ValueError):
    pass


def transition(current: ValidationStatus, new: ValidationStatus) -> ValidationStatus:
    if new not in TRANSITIONS[current]:
        raise InvalidTransitionError(f"{current.value} -> {new.value} is not allowed")
    return new


@dataclass(frozen=True, slots=True)
class StrategyDeployment:
    version: str
    status: ValidationStatus
    label_ar: str  # short label shown next to every signal
    signal_timeframes: frozenset[str]  # directional live signals allowed here
    note_ar: str
    evidence: str  # where the decision is documented

    def signal_capable(self, timeframe: str) -> bool:
        return self.status is not ValidationStatus.REJECTED and timeframe in self.signal_timeframes

    def apply(self, ev: SignalEvaluation) -> SignalEvaluation:
        """Downgrade a directional evaluation on a research-only timeframe (pure)."""
        if ev.signal_class is SignalClass.NEUTRAL or self.signal_capable(ev.timeframe):
            return ev
        return replace(
            ev, signal_class=SignalClass.NEUTRAL, side=None, neutral_reason=RESEARCH_ONLY_REASON
        )

    def info(self, timeframe: str) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status.value,
            "status_ar": STATUS_AR[self.status],
            "label_ar": self.label_ar,
            "forward_test": self.status is ValidationStatus.FORWARD_TEST,
            "signal_capable": self.signal_capable(timeframe),
            "note_ar": self.note_ar,
        }


# The frozen Phase 4 baseline. Phase 4.1 walk-forward research found no robust edge
# (docs/research.md), so it stays UNPROVEN / experimental. 1m and 10m are research-only
# (costs exceed practical risk on 1m; 10m duplicates 5m/15m information). 5m is
# research-only because ~90% of its structural plans cannot clear the cost floor and its
# validation results were negative.
PHASE4_BASELINE = StrategyDeployment(
    version=strategy_version(DEFAULT_SIGNAL_CONFIG),
    status=ValidationStatus.UNPROVEN,
    label_ar="تجريبي",
    signal_timeframes=frozenset({"15m", "30m", "1h"}),
    note_ar="استراتيجية تجريبية لم تُثبت أفضلية تاريخية بعد التكاليف — ليست توصية.",
    evidence="docs/research.md",
)

ACTIVE_DEPLOYMENT = PHASE4_BASELINE
