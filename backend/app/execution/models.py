"""Execution-layer models (1m / 5m / 10m entry timing for an active Strategy 4.2 setup).

The execution layer never creates an independent trade thesis. Direction, setup, invalidation
and targets come from the parent Strategy 4.2 signal (15m / 30m / 1h). A lower-timeframe BUY /
SELL is an *entry-timing confirmation* for that parent. Times are UTC epoch seconds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

EXECUTION_VERSION = "wese-trade-execution-1.2"
EXECUTION_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "10m")


class Decision(StrEnum):
    BUY = "BUY"
    SELL = "SELL"
    WAIT = "WAIT"
    ENTRY_MISSED = "ENTRY_MISSED"
    NO_SETUP = "NO_SETUP"


class ExecState(StrEnum):
    """Lifecycle of a confirmed execution signal (persisted)."""

    READY = "ready"  # confirmed on a closed candle; manual entry possible until valid_until
    ACTIVE = "active"  # price traded at the entry after confirmation
    TP1_HIT = "tp1_hit"
    TP2_HIT = "tp2_hit"
    TP3_HIT = "tp3_hit"
    STOPPED = "stopped"
    EXPIRED = "expired"  # parent ended before entry, or the maximum holding time passed
    ENTRY_MISSED = "entry_missed"  # entry window passed, or price ran to TP1 without a fill

    @property
    def is_final(self) -> bool:
        return self in (
            ExecState.TP3_HIT,
            ExecState.STOPPED,
            ExecState.EXPIRED,
            ExecState.ENTRY_MISSED,
        )


DECISION_AR = {
    Decision.BUY: "شراء",
    Decision.SELL: "بيع",
    Decision.WAIT: "انتظر",
    Decision.ENTRY_MISSED: "فاتت منطقة الدخول",
    Decision.NO_SETUP: "لا توجد فرصة مناسبة حالياً",
}
STATE_AR = {
    "waiting": "بانتظار التوقيت",
    ExecState.READY: "جاهز للدخول",
    ExecState.ACTIVE: "صفقة نشطة",
    ExecState.TP1_HIT: "تحقق الهدف 1",
    ExecState.TP2_HIT: "تحقق الهدف 2",
    ExecState.TP3_HIT: "تحقق الهدف 3",
    ExecState.STOPPED: "ضُرب وقف الخسارة",
    ExecState.EXPIRED: "انتهت صلاحية الإشارة",
    ExecState.ENTRY_MISSED: "فاتت منطقة الدخول",
}


@dataclass(frozen=True, slots=True)
class ParentSetup:
    """The active Strategy 4.2 signal an execution decision belongs to."""

    signal_id: str
    strategy: str  # display name, e.g. "Wese Trade Forward 4.2"
    strategy_version: str  # e.g. wese-trade-forward-4.2-a03e20f1d4
    symbol: str
    timeframe: str  # 15m | 30m | 1h
    side: int  # +1 long, -1 short
    family: str
    score: float
    state: str  # parent lifecycle state (confirmed / active / tp1_hit / ...)
    confirmed_time: int
    entry_low: float
    entry_high: float
    entry: float  # parent preferred entry
    stop: float
    invalidation: float
    targets: tuple[float, float, float]

    @property
    def risk(self) -> float:
        return abs(self.entry - self.stop)

    @property
    def is_open(self) -> bool:
        return self.state not in ("tp3_hit", "stopped", "invalidated", "expired", "closed")


@dataclass(frozen=True, slots=True)
class Level:
    price: float
    strength: float
    grade: str  # strong | medium | weak
    kind: str  # support | resistance


@dataclass(frozen=True, slots=True)
class Features:
    """Closed-candle execution evidence for one stream (built from the canonical analyzer)."""

    index: int  # absolute bar index of the closed candle in the analyzer series
    time: int  # open time of the closed candle
    close_time: int
    open: float
    high: float
    low: float
    close: float
    prev_close: float
    atr: float
    ema20: float | None
    ema50: float | None
    ema200: float | None
    ema20_prev: float | None  # EMA20 one candle earlier (reclaim detection)
    ema_stack: str  # bullish | bearish | mixed
    regime: str  # canonical MarketRegime value
    direction: str  # bullish | bearish | neutral (canonical trend direction)
    rsi: float | None
    rsi_slope: float | None
    structure_events: tuple[tuple[int, str, str], ...]  # (bar index, BOS|CHOCH, bullish|bearish)
    sweeps: tuple[tuple[int, str, float], ...]  # (bar index, buy_side|sell_side, level)
    supports: tuple[Level, ...]  # nearest first, below price
    resistances: tuple[Level, ...]  # nearest first, above price
    swing_low: float | None  # latest confirmed internal swing low / high (structural stop)
    swing_high: float | None
    tick: float


@dataclass(frozen=True, slots=True)
class Micro:
    """Live microstructure snapshot (optional; absent = candle/structure logic only)."""

    status: str  # ok | degraded | stale | unavailable
    spread_bp: float | None = None
    spread_normal_bp: float | None = None
    book_imbalance: float | None = None  # top-5 size imbalance, -1..1
    flow_imbalance: float | None = None  # aggressive buy-sell share over the last minute, -1..1
    book_age_s: float | None = None
    trade_age_s: float | None = None
    reasons: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return self.status in ("ok", "degraded")


@dataclass(frozen=True, slots=True)
class Plan:
    side: int
    entry: float  # final recommended manual entry
    parent_entry: float
    stop: float
    parent_stop: float
    stop_source: str
    targets: tuple[float, float, float]
    target_sources: tuple[str, str, str]

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
    """The execution decision for one closed candle of one stream."""

    symbol: str
    timeframe: str
    candle_time: int | None
    decision: Decision
    score: float  # «قوة توقيت الدخول» 0-100 (execution conditions; NOT a win probability)
    side: int  # +1 / -1 from the parent, 0 without a parent
    parent: ParentSetup | None
    plan: Plan | None  # preview plan (WAIT) or the confirmed plan (BUY / SELL)
    reasons: tuple[str, ...]  # Arabic, positive evidence first
    cautions: tuple[str, ...]  # Arabic, what is missing / against
    headline: str  # Arabic one-line explanation
    components: dict[str, float] = field(default_factory=dict)
    micro: Micro | None = None
    trigger: str | None = None  # evidence that fired the confirmation on this candle


@dataclass(slots=True)
class ExecutionSignal:
    """A confirmed execution signal. Fields up to `micro` are frozen at confirmation."""

    id: str
    symbol: str
    timeframe: str
    side: int
    score: float
    confirmed_time: int  # close time of the confirmation candle
    candle_time: int  # open time of the confirmation candle (marker position)
    valid_until: int
    plan: Plan
    parent: ParentSetup
    reasons: tuple[str, ...]
    trigger: str
    execution_version: str = EXECUTION_VERSION
    micro: dict[str, Any] | None = None
    # --- lifecycle (forward-only) --------------------------------------------------------
    state: ExecState = ExecState.READY
    state_time: int = 0
    entered_time: int | None = None
    targets_hit: int = 0
    closed_time: int | None = None
    bars: int = 0
    cursor: int = 0  # close time of the last candle applied to the lifecycle
    history: list[tuple[int, str]] = field(default_factory=list)

    @property
    def is_open(self) -> bool:
        return not self.state.is_final
