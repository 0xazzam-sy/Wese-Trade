"""Signal engine models.

Immutable: evaluation results, trade plans, the original fields of a confirmed signal.
Mutable: only the lifecycle part of a `Signal` (state, fills, exits, realized R).
Times are UTC epoch seconds. Prices are float64 analysis values (display rounding uses
the instrument tick size); outcomes are measured in R-multiples, never account P&L.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.analysis.models import AnalysisSnapshot
from app.analysis.series import Bar
from app.signal_engine.enums import (
    EntryModel,
    ExitReason,
    SetupFamily,
    Side,
    SignalClass,
    SignalState,
)


@dataclass(frozen=True, slots=True)
class SignalInput:
    """Everything the pure engine may read. Built from one analyzer state."""

    snapshot: AnalysisSnapshot
    recent_bars: tuple[Bar, ...]  # last closed bars, oldest first (for touches / pullbacks)
    tick_size: float
    developing: bool = False  # True: evaluate the forming candle (never a trade)
    market_stale: bool = False
    symbol_active: bool = True


@dataclass(frozen=True, slots=True)
class Component:
    name: str
    value: float  # 0..1
    weight: float  # max points
    points: float  # value * weight (after category caps)


@dataclass(frozen=True, slots=True)
class Penalty:
    code: str
    points: float
    reason: str  # Arabic


@dataclass(frozen=True, slots=True)
class Trigger:
    id: str  # stable id of the structure event (or developing marker)
    time: int  # open time of the trigger candle
    layer: str
    type: str  # BOS | CHOCH
    direction: str  # bullish | bearish
    displacement: float | None
    relative_volume: float | None
    level: float


@dataclass(frozen=True, slots=True)
class Hypothesis:
    family: SetupFamily
    side: Side
    trigger: Trigger
    components: tuple[Component, ...]
    penalties: tuple[Penalty, ...]
    base_score: float  # normalized 0-100 before penalties
    score: float  # 0-100 after penalties (confluence, NOT probability)
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    regime: str | None


@dataclass(frozen=True, slots=True)
class Target:
    price: float
    rr: float
    source: str


@dataclass(frozen=True, slots=True)
class TradePlan:
    entry_model: EntryModel
    entry_low: float
    entry_high: float
    preferred_entry: float
    stop: float
    invalidation: float  # close beyond this before entry invalidates the setup
    stop_source: str
    risk: float  # |preferred_entry - stop| in price
    risk_atr: float
    targets: tuple[Target, Target, Target]

    def rr(self) -> tuple[float, float, float]:
        return (self.targets[0].rr, self.targets[1].rr, self.targets[2].rr)


@dataclass(frozen=True, slots=True)
class SignalEvaluation:
    symbol: str
    timeframe: str
    candle_time: int | None  # last CLOSED candle (confirmed) / forming candle (developing)
    developing: bool
    signal_class: SignalClass
    side: Side | None
    score: float  # chosen side's score (0 for NEUTRAL without a hypothesis)
    bull_score: float
    bear_score: float
    hypothesis: Hypothesis | None  # chosen
    best_bull: Hypothesis | None
    best_bear: Hypothesis | None
    plan: TradePlan | None
    neutral_reason: str | None  # Arabic, when NEUTRAL
    strategy_version: str
    evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def is_trade(self) -> bool:
        return self.signal_class is not SignalClass.NEUTRAL and self.plan is not None


@dataclass(slots=True)
class Signal:
    """A confirmed signal. Fields up to `strategy_version` are frozen at confirmation."""

    id: str
    symbol: str
    timeframe: str
    side: Side
    signal_class: SignalClass
    family: SetupFamily
    score: float
    trigger_id: str
    trigger_time: int  # open time of the trigger candle
    confirmed_time: int  # close time of the trigger candle (= confirmation moment)
    plan: TradePlan
    components: tuple[Component, ...]
    penalties: tuple[Penalty, ...]
    positive: tuple[str, ...]
    negative: tuple[str, ...]
    evidence: dict[str, Any]
    strategy_version: str
    regime: str | None
    # --- lifecycle (mutable, forward-only) -------------------------------------------------
    state: SignalState = SignalState.CONFIRMED
    state_time: int = 0
    entered_time: int | None = None
    entry_price: float | None = None  # actual fill (incl. slippage for market entries)
    remaining: float = 1.0
    targets_hit: int = 0
    exits: list[tuple[float, float, str]] = field(default_factory=list)  # fraction, price, why
    exit_reason: ExitReason | None = None
    closed_time: int | None = None
    ambiguous: bool = False
    bars_held: int = 0
    bars_pending: int = 0
    gross_r: float | None = None
    net_r: float | None = None
    mfe_r: float = 0.0
    mae_r: float = 0.0
    history: list[tuple[int, str]] = field(default_factory=list)  # (time, state)

    @property
    def is_open(self) -> bool:
        return not self.state.is_final

    @property
    def entered(self) -> bool:
        return self.entered_time is not None
