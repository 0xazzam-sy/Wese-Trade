"""Central signal configuration. Every weight, threshold and rule constant lives here.

`strategy_version` (name + hash of this config AND the Phase 3 analysis config) is stored
with every signal and backtest so results can never silently change meaning.
Values marked [validated] were chosen on the development split only (docs/backtesting.md).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from app.analysis.config import DEFAULT_CONFIG as ANALYSIS_DEFAULT
from app.analysis.config import AnalysisConfig

ENGINE_VERSION = "4.0"


@dataclass(frozen=True, slots=True)
class Weights:
    """Maximum points per category (normalized over the categories available)."""

    htf: float = 20.0
    structure: float = 20.0
    liquidity: float = 15.0
    location: float = 15.0
    trend: float = 10.0
    displacement: float = 7.0
    volume: float = 5.0
    momentum: float = 5.0
    candle: float = 3.0
    # displacement + volume + candle all describe the SAME trigger candle: cap their sum.
    trigger_cluster_cap: float = 10.0


@dataclass(frozen=True, slots=True)
class Penalties:
    htf_strong_opposition: float = 15.0
    htf_strong_opposition_reversal: float = 8.0  # reversal with an aligned swing CHoCH
    htf_first_opposed: float = 8.0
    extreme_location: float = 8.0
    overextended: float = 6.0
    extreme_volatility: float = 6.0
    volume_contradiction: float = 4.0
    volume_contradiction_breakout: float = 8.0
    momentum_opposed: float = 5.0
    opposite_divergence: float = 4.0
    adverse_sweep: float = 6.0
    opposing_zone_ahead: float = 5.0
    transitional_regime: float = 4.0


@dataclass(frozen=True, slots=True)
class SignalConfig:
    name: str = "wese-trade-signal"
    weights: Weights = field(default_factory=Weights)
    penalties: Penalties = field(default_factory=Penalties)

    # --- classification ------------------------------------------------------------
    # [validated] 75: dev calibration rose from 75-79 to 80-89; 70-74 added only cost.
    regular_threshold: float = 75.0
    strong_threshold: float = 85.0
    # [validated] DISABLED: 85+ was better on the dev split but WORSE on the holdout, so a
    # STRONG tier is not supported by evidence (docs/backtesting.md). Classes stay defined.
    strong_enabled: bool = False
    min_score_spread: float = 10.0  # |bull - bear| below this -> NEUTRAL (conflicted)
    evaluation_floor: float = 40.0  # hypotheses below this are not given a trade plan
    timeframe_threshold_offsets: dict[str, float] = field(default_factory=dict)

    enabled_families: tuple[str, ...] = (
        "TREND_CONTINUATION",
        "PULLBACK_CONTINUATION",
        "BREAKOUT_CONTINUATION",
        "LIQUIDITY_REVERSAL",
    )

    # --- eligibility -----------------------------------------------------------------------
    block_atr_percentile: float = 99.0
    require_htf_context: bool = True

    # --- setup families --------------------------------------------------------------------
    recent_bos_bars: int = 30
    recent_swing_choch_bars: int = 50
    pullback_lookback_bars: int = 12
    reversal_sweep_bars: int = 10
    breakout_min_displacement: float = 50.0
    breakout_min_relvol: float = 1.2
    breakout_min_close_location: float = 0.5
    overextension_atr: float = 3.0
    zone_min_quality: float = 40.0
    fvg_max_filled: float = 0.75
    touch_lookback_bars: int = 3
    extreme_premium_position: float = 85.0
    extreme_discount_position: float = 15.0
    adverse_sweep_bars: int = 5
    target_liquidity_atr: float = 4.0

    # --- trade plan ------------------------------------------------------------------------
    stop_buffer_ticks: int = 3
    stop_buffer_atr: float = 0.1
    min_stop_atr: float = 0.5
    max_stop_atr: float = 3.0
    min_stop_ticks: int = 5
    # [validated] risk must be >= 5x the round-trip trading cost: improved every dev variant
    min_risk_cost_multiple: float = 5.0
    zone_entry_max_atr: float = 1.0
    target_front_run_atr: float = 0.05
    tp_min_rr: float = 0.75
    tp_max_rr: float = 8.0
    tp_merge_rr: float = 0.3
    tp1_max_structural_rr: float = 2.0
    min_headroom_rr: float = 0.75
    min_tp2_rr: float = 1.5

    # --- lifecycle -----------------------------------------------------------------------
    cooldown_bars: int = 5
    allow_opposite_strong_override: bool = True
    entry_expiry_bars: int = 6
    max_hold_bars: int = 48
    target_fractions: tuple[float, float, float] = (1 / 3, 1 / 3, 1 / 3)
    move_stop_to_entry_after_tp1: bool = False

    # --- costs (R-multiple evaluation; never account P&L, never leverage) -----------------
    fee_rate: float = 0.0005  # per side, taker-like (conservative default)
    maker_fee_rate: float = 0.0002  # limit entries / take-profits
    slippage_rate: float = 0.0002  # market entries and stop/time exits

    # --- developing ----------------------------------------------------------------------
    developing_min_interval_seconds: float = 5.0

    def threshold_for(self, timeframe: str) -> tuple[float, float]:
        offset = self.timeframe_threshold_offsets.get(timeframe, 0.0)
        return self.regular_threshold + offset, self.strong_threshold + offset

    def round_trip_cost_rate(self) -> float:
        return 2 * self.fee_rate + 2 * self.slippage_rate

    def with_changes(self, **changes: Any) -> SignalConfig:
        return replace(self, **changes)


def _stable(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, default=str, separators=(",", ":"))


def strategy_version(config: SignalConfig, analysis: AnalysisConfig = ANALYSIS_DEFAULT) -> str:
    digest = hashlib.sha256(
        _stable(
            {"engine": ENGINE_VERSION, "signal": asdict(config), "analysis": asdict(analysis)}
        ).encode()
    ).hexdigest()[:10]
    return f"{config.name}-{ENGINE_VERSION}-{digest}"


DEFAULT_SIGNAL_CONFIG = SignalConfig()
