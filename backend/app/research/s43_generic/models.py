"""Strategy 4.3 models: weighted market evidence -> opportunity (side, setup, tier, plan).

Strategy 4.2 (`wese-trade-forward-4.2-a03e20f1d4`) is untouched and stays the frozen
baseline. 4.3 is a separately versioned strategy for practical opportunity coverage:
few hard blockers; everything else moves the BUY / SELL scores. Scores are confluence
values out of 100 («قوة الإشارة»), never probabilities. Times are UTC epoch seconds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

PRIMARY_TIMEFRAMES: tuple[str, ...] = ("15m", "30m", "1h")


class Family(StrEnum):
    TREND_CONTINUATION = "TREND_CONTINUATION"
    PULLBACK = "PULLBACK"
    BREAKOUT = "BREAKOUT"
    BREAKOUT_RETEST = "BREAKOUT_RETEST"
    MOMENTUM = "MOMENTUM"
    SUPPORT_REACTION = "SUPPORT_REACTION"
    RESISTANCE_REACTION = "RESISTANCE_REACTION"
    LIQUIDITY_SWEEP = "LIQUIDITY_SWEEP"
    RANGE_EDGE = "RANGE_EDGE"
    STRUCTURE_REVERSAL = "STRUCTURE_REVERSAL"


FAMILY_AR: dict[str, str] = {
    "TREND_CONTINUATION": "استمرار الاتجاه",
    "PULLBACK": "ارتداد تصحيحي",
    "BREAKOUT": "اختراق",
    "BREAKOUT_RETEST": "اختراق وإعادة اختبار",
    "MOMENTUM": "استمرار الزخم",
    "SUPPORT_REACTION": "ارتداد من دعم",
    "RESISTANCE_REACTION": "ارتداد من مقاومة",
    "LIQUIDITY_SWEEP": "سحب سيولة وانعكاس",
    "RANGE_EDGE": "انعكاس من حافة النطاق",
    "STRUCTURE_REVERSAL": "انعكاس الهيكل",
}


class Regime(StrEnum):
    UPTREND = "UPTREND"
    DOWNTREND = "DOWNTREND"
    RANGE = "RANGE"
    COMPRESSION = "COMPRESSION"
    BREAKOUT = "BREAKOUT"
    TRANSITION = "TRANSITION"


REGIME_AR = {
    "UPTREND": "اتجاه صاعد",
    "DOWNTREND": "اتجاه هابط",
    "RANGE": "نطاق عرضي",
    "COMPRESSION": "انضغاط",
    "BREAKOUT": "اختراق / توسع",
    "TRANSITION": "مرحلة انتقالية",
}

TIERS: tuple[str, ...] = ("A+", "A", "B", "C")
TIER_AR = {"A+": "استثنائية", "A": "قوية", "B": "جيدة", "C": "مقبولة", "WAIT": "انتظار"}


@dataclass(frozen=True, slots=True)
class Setup:
    family: Family
    side: int  # +1 long, -1 short
    strength: float  # 0..1
    anchor: float | None  # structural invalidation reference (swing / sweep / level)
    note: str  # Arabic


@dataclass(frozen=True, slots=True)
class Plan:
    side: int
    entry: float
    stop: float
    targets: tuple[float, float, float]
    target_sources: tuple[str, str, str]
    stop_source: str

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def rr(self) -> tuple[float, float, float]:
        r = self.risk
        if r <= 0:
            return (0.0, 0.0, 0.0)
        return tuple(round(self.side * (t - self.entry) / r, 2) for t in self.targets)  # type: ignore[return-value]


@dataclass(frozen=True, slots=True)
class Evaluation:
    """Strategy 4.3 on one CLOSED candle of one stream."""

    symbol: str
    timeframe: str
    candle_time: int  # open time of the closed candle
    close_time: int
    price: float
    buy_score: float
    sell_score: float
    side: int  # +1 / -1 for an opportunity, 0 = WAIT
    score: float  # the chosen side's score (or the larger one on WAIT)
    tier: str  # A+ | A | B | C | WAIT
    setup: Setup | None
    plan: Plan | None
    regime: str
    trend: str  # BULLISH | BEARISH | MIXED
    blockers: tuple[str, ...]  # hard blockers (Arabic)
    reasons: tuple[str, ...]  # supporting evidence for the chosen side (Arabic)
    cautions: tuple[str, ...]  # evidence against / what is weak (Arabic)
    components: dict[str, float] = field(default_factory=dict)
    trigger_id: str | None = None  # stable id of the setup trigger (dedupe)

    @property
    def actionable(self) -> bool:
        return self.side != 0 and self.tier != "WAIT" and self.plan is not None
