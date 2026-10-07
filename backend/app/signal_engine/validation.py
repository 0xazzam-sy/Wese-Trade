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
DISABLED_FAMILY_REASON = "نوع إعداد تجريبي معطّل للإشارات — لم يُظهر أفضلية في البحث"


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
    # Families kept in the engine (still evaluated, visible in details) but never emitted
    # as directional signals: EXPERIMENTAL / DISABLED_FOR_SIGNALS (docs/research.md).
    disabled_families: frozenset[str] = frozenset()
    # Reason shown when a directional evaluation is downgraded on a non-signal timeframe.
    inactive_reason: str = ""

    def signal_capable(self, timeframe: str) -> bool:
        return self.status is not ValidationStatus.REJECTED and timeframe in self.signal_timeframes

    def apply(self, ev: SignalEvaluation) -> SignalEvaluation:
        """Downgrade a directional evaluation on a research-only timeframe or from a
        disabled family (pure; the hypothesis stays attached for transparency)."""
        if ev.signal_class is SignalClass.NEUTRAL:
            return ev
        if not self.signal_capable(ev.timeframe):
            reason = self.inactive_reason or RESEARCH_ONLY_REASON
        elif ev.hypothesis is not None and ev.hypothesis.family.value in self.disabled_families:
            reason = DISABLED_FAMILY_REASON
        else:
            return ev
        return replace(ev, signal_class=SignalClass.NEUTRAL, side=None, neutral_reason=reason)

    def info(self, timeframe: str) -> dict[str, Any]:
        return {
            "version": self.version,
            "status": self.status.value,
            "status_ar": STATUS_AR[self.status],
            "label_ar": self.label_ar,
            "forward_test": self.status is ValidationStatus.FORWARD_TEST,
            "signal_capable": self.signal_capable(timeframe),
            "note_ar": self.note_ar,
            "fingerprint": None,
            "name": None,
            "score_calibrated": False,
            "scope_note_ar": None
            if self.signal_capable(timeframe)
            else (
                TIMEFRAME_INACTIVE_AR
                if timeframe in RESEARCH_ONLY_TIMEFRAMES
                else SYMBOL_INACTIVE_AR
            ),
        }


# The frozen Phase 4 baseline. Phase 4.1 walk-forward research found no robust edge
# (docs/research.md), so it stays UNPROVEN / experimental:
# * 1m: structurally unsuitable (98.5% of structural plans cannot clear the cost floor);
# * 5m: negative in every validation window (-0.125R baseline, -0.046R trend-only);
# * 10m: research-only (anchors only, failed acceptance);
# * LIQUIDITY_REVERSAL and BREAKOUT_CONTINUATION: negative in the pre-period and in every
#   validation window (breakout negative even before costs) -> disabled for signals.
PHASE4_BASELINE = StrategyDeployment(
    version=strategy_version(DEFAULT_SIGNAL_CONFIG),
    status=ValidationStatus.UNPROVEN,
    label_ar="تجريبي",
    signal_timeframes=frozenset({"15m", "30m", "1h"}),
    note_ar="استراتيجية تجريبية لم تُثبت أفضلية تاريخية بعد التكاليف — ليست توصية.",
    evidence="docs/research.md",
    disabled_families=frozenset({"LIQUIDITY_REVERSAL", "BREAKOUT_CONTINUATION"}),
)

RESEARCH_ONLY_TIMEFRAMES = frozenset({"1m", "5m", "10m"})
TIMEFRAME_INACTIVE_AR = "هذا الفريم غير مفعّل للإشارات حالياً"
BASELINE_INACTIVE_AR = (
    "الإشارات الاتجاهية تصدر فقط من استراتيجية الاختبار المباشر لرموز وفريمات محددة"
)
SYMBOL_INACTIVE_AR = "هذا الرمز أو الفريم خارج نطاق الاختبار المباشر — لا إشارات اتجاهية"

# Phase 4.2: directional signals come ONLY from the frozen forward-test candidate
# (app.forward_test) on its universe x 15m/30m/1h. The unproven baseline keeps evaluating
# everywhere else for transparency, but never emits BUY/SELL.
ACTIVE_DEPLOYMENT = replace(
    PHASE4_BASELINE,
    signal_timeframes=frozenset(),
    note_ar="الاستراتيجية الأساسية غير مُثبتة — لا تُصدر إشارات اتجاهية.",
    inactive_reason=BASELINE_INACTIVE_AR,
)


@dataclass(frozen=True, slots=True)
class ResearchCandidate:
    """A research strategy version under study. Never emitted live while TESTING."""

    version: str
    status: ValidationStatus
    definition: str
    verdict: str


# Exploratory post-hoc candidate (docs/research.md §8): positive in W1-W3 but its grid was
# designed after seeing those windows and it was NEGATIVE in the pre-period. It stays
# TESTING until it passes a prospective test on data after 2026-10-04.
RESEARCH_CANDIDATES = (
    ResearchCandidate(
        version="wese-trade-research-4.1-c590e82e3a",
        status=ValidationStatus.TESTING,
        definition="TREND_CONTINUATION only, 15m/30m/1h, threshold 75, no range/transitional, "
        "retrace entry (confirmation-candle midpoint limit), runner exit (1/2 TP1, 1/2 TP3)",
        verdict="not promoted: post-hoc design, negative pre-period (-0.068R, n=252)",
    ),
)


@dataclass(frozen=True, slots=True)
class LowerTimeframeSlot:
    """Reserved place for a FUTURE lower-timeframe (1m/5m/10m) research strategy.

    It is deliberately inactive. A lower-timeframe strategy must be its own, separately
    versioned ResearchCandidate (never a tweak of the frozen forward-test strategy) and
    may emit live signals only after it reaches FORWARD_TEST through the documented state
    machine. Until then these timeframes show analysis only.
    """

    timeframes: frozenset[str] = RESEARCH_ONLY_TIMEFRAMES
    candidate: ResearchCandidate | None = None
    live_enabled: bool = False

    def __post_init__(self) -> None:
        if self.live_enabled and (
            self.candidate is None or self.candidate.status is not ValidationStatus.FORWARD_TEST
        ):
            raise ValueError("lower-timeframe signals require a FORWARD_TEST candidate")

    def signal_capable(self, timeframe: str) -> bool:
        return self.live_enabled and timeframe in self.timeframes


LOWER_TIMEFRAME_SLOT = LowerTimeframeSlot()
