"""Wese Trade Strategy 4.3: the frozen definition, its version, tiers and display labels.

4.3 is built on the same canonical pipeline as Strategy 4.2 (MarketAnalyzer snapshot ->
SignalEngine weighted evidence -> structural plans -> SignalTracker lifecycle with costs),
but selects for PRACTICAL AVAILABILITY instead of near-perfect setups:

* families: trend continuation AND pullback continuation (4.2: trend continuation only);
* threshold: weighted-evidence score >= 65 (4.2: 75), graded into tiers A+/A/B/C;
* regimes: only a RANGING regime is excluded (4.2 also excluded TRANSITIONAL);
* BUY / SELL margin: the chosen side must lead the opposite side by >= 10 points;
* hard blockers are only the engine gates (data not ready / stale / inactive symbol /
  catastrophic volatility / no plan with valid geometry); everything else moves the score.

The configuration was chosen on development data, checked on validation and evaluated on
the holdout exactly once (docs/strategy-4.3.md). Strategy 4.2
(`wese-trade-forward-4.2-a03e20f1d4`) is untouched and keeps running as the baseline.
Scores are weighted-evidence values out of 100 («قوة الإشارة»), never probabilities.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from typing import Any

from app.analysis.config import DEFAULT_CONFIG as ANALYSIS_CONFIG
from app.analysis.multi_timeframe.context import context_timeframes
from app.forward_test.candidate import UNIVERSE as CORE_UNIVERSE
from app.forward_test.candidate import candidate
from app.market_data.timeframes import Timeframe
from app.research.simulate import COSTS, Variant

NAME = "Wese Trade Strategy 4.3"
VERSION_PREFIX = "wese-trade-strategy-4.3"
TIMEFRAMES: tuple[str, ...] = ("15m", "30m", "1h")
FAMILIES: tuple[str, ...] = ("TREND_CONTINUATION", "PULLBACK_CONTINUATION")

# Tier floors on the weighted-evidence score (calibrated on development data; the 65 floor
# keeps opportunities available across the universe, A/A+ carry the measured edge).
TIER_FLOORS: tuple[tuple[str, float], ...] = (("A+", 82.0), ("A", 75.0), ("B", 70.0), ("C", 65.0))
TIER_AR = {"A+": "استثنائية", "A": "قوية", "B": "جيدة", "C": "مقبولة", "WAIT": "انتظار"}
TIER_RANK = {"A+": 4, "A": 3, "B": 2, "C": 1, "WAIT": 0}

# Scanner universe: the liquid core (Phase 4.1 methodology, never chosen by performance)
# plus the most liquid active USDT perpetuals by 24h traded value at startup.
SCANNER_SIZE = 30

FAMILY_AR = {
    "TREND_CONTINUATION": "استمرار الاتجاه",
    "PULLBACK_CONTINUATION": "ارتداد تصحيحي مع الاتجاه",
    "BREAKOUT_CONTINUATION": "اختراق",
    "LIQUIDITY_REVERSAL": "سحب سيولة وانعكاس",
}

# Canonical MarketRegime -> the 4.3 display regime.
REGIME_43 = {
    "strong_uptrend": "UPTREND",
    "uptrend": "UPTREND",
    "strong_downtrend": "DOWNTREND",
    "downtrend": "DOWNTREND",
    "ranging": "RANGE",
    "low_volatility": "COMPRESSION",
    "high_volatility": "BREAKOUT",
    "transitional": "TRANSITION",
}
REGIME_AR = {
    "UPTREND": "اتجاه صاعد",
    "DOWNTREND": "اتجاه هابط",
    "RANGE": "نطاق عرضي",
    "COMPRESSION": "انضغاط",
    "BREAKOUT": "توسع / اختراق",
    "TRANSITION": "مرحلة انتقالية",
}


def tier(score: float) -> str:
    for name, floor in TIER_FLOORS:
        if score >= floor:
            return name
    return "WAIT"


def variant() -> Variant:
    """4.3 = the 4.2 research variant with the practical-availability selection."""
    return replace(
        candidate(),
        name="strategy-4.3",
        families=FAMILIES,
        threshold=TIER_FLOORS[-1][1],
        spread=10.0,
        excluded_regimes=("range",),
        notes="Strategy 4.3: practical availability, tiers A+/A/B/C (docs/strategy-4.3.md)",
    )


def frozen_config(v: Variant | None = None) -> dict[str, Any]:
    v = v or variant()
    return {
        "name": NAME,
        "variant": v.definition(),
        "signal_config": asdict(v.tracker_config()),
        "analysis_config": asdict(ANALYSIS_CONFIG),
        "timeframes": list(TIMEFRAMES),
        "context_timeframes": {
            tf: [c.value for c in context_timeframes(Timeframe(tf))] for tf in TIMEFRAMES
        },
        "tiers": [list(t) for t in TIER_FLOORS],
        "cost_model": asdict(COSTS[v.costs]),
        "entry_model": "retrace: limit at the confirmation-candle midpoint (cost floor kept)",
        "target_model": "structural targets; runner exit 1/2 at TP1, 1/2 at TP3, 96-bar hold",
        "protocol": "live-v1: confirmed only from candles observed closing live",
    }


def strategy_version(config: dict[str, Any] | None = None) -> str:
    raw = json.dumps(config or frozen_config(), sort_keys=True, default=str, separators=(",", ":"))
    return f"{VERSION_PREFIX}-{hashlib.sha256(raw.encode()).hexdigest()[:10]}"


def fingerprint(version: str) -> str:
    return f"4.3-{version.rsplit('-', 1)[-1][:7]}"


__all__ = [
    "CORE_UNIVERSE",
    "FAMILIES",
    "FAMILY_AR",
    "NAME",
    "REGIME_43",
    "REGIME_AR",
    "SCANNER_SIZE",
    "TIER_AR",
    "TIER_FLOORS",
    "TIER_RANK",
    "TIMEFRAMES",
    "fingerprint",
    "frozen_config",
    "strategy_version",
    "tier",
    "variant",
]
