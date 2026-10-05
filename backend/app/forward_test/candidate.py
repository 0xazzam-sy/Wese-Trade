"""The frozen forward-test candidate and its immutable strategy version.

The candidate is LOADED from the persisted research definition and verified by its
research version hash (`wese-trade-research-4.1-c590e82e3a`); it is never recreated by
hand. The forward-test version hashes everything that determines a signal or its R:
the research variant definition, the full signal config (thresholds, plan rules,
lifecycle, costs), the analysis config, the timeframe policy, the symbol universe, the
cost model and the forward-test protocol (start boundary rule, pass/fail criteria).
Any change produces a NEW version; an active run can never change version.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from typing import Any

from app.analysis.config import DEFAULT_CONFIG as ANALYSIS_CONFIG
from app.analysis.multi_timeframe.context import context_timeframes
from app.market_data.timeframes import Timeframe
from app.research.candidates import by_version
from app.research.simulate import COSTS, Variant

RESEARCH_VERSION = "wese-trade-research-4.1-c590e82e3a"
FORWARD_VERSION_PREFIX = "wese-trade-forward-4.2"
DISPLAY_NAME = "Wese Trade Forward 4.2"
TIMEFRAMES: tuple[str, ...] = ("15m", "30m", "1h")

# Same objective liquidity methodology as Phase 4.1 (app.research.universe): anchors +
# the most liquid crypto USDT perpetuals by 30-day mean quote volume, listed >= 400 days.
# The Phase 4.1 selection (2026-10-04) is reused unchanged; never chosen by performance.
UNIVERSE: tuple[str, ...] = (
    "BTCUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "XRPUSDT",
    "DOGEUSDT",
    "HYPEUSDT",
    "NEARUSDT",
    "UNIUSDT",
    "PUMPUSDT",
    "SUIUSDT",
    "PEPEUSDT",
    "ARBUSDT",
)


@dataclass(frozen=True, slots=True)
class Criteria:
    """Conservative forward-test decision rules (docs/forward-testing.md §8)."""

    min_closed_trades: int = 150
    min_days: int = 30
    min_profit_factor: float = 1.1
    max_drawdown_floor_r: float = 15.0  # max DD <= max(floor, fraction * trades)
    max_drawdown_fraction: float = 0.2
    recent_trades: int = 30  # "recent" window shown + deterioration check
    recent_min_expectancy: float = -0.10
    fail_min_trades: int = 75  # never fail on less evidence than this
    fail_expectancy: float = -0.10
    fail_profit_factor: float = 0.85


CRITERIA = Criteria()
# Forward-test start rule: only candles that OPEN at or after `started_at` can produce
# signals (their whole range is post-start). Older candles are warm-up only.
PROTOCOL = "forward-protocol-v1: open_time>=started_at; no new signals from catch-up candles"


def candidate() -> Variant:
    v = by_version(RESEARCH_VERSION)
    if v.version != RESEARCH_VERSION:  # pragma: no cover - by_version guarantees it
        raise RuntimeError("frozen candidate definition changed")
    return v


def frozen_config(v: Variant | None = None) -> dict[str, Any]:
    v = v or candidate()
    cost = COSTS[v.costs]
    return {
        "research_version": v.version,
        "research_name": v.name,
        "variant": v.definition(),
        "signal_config": asdict(v.tracker_config()),
        "analysis_config": asdict(ANALYSIS_CONFIG),
        "timeframes": list(TIMEFRAMES),
        "context_timeframes": {
            tf: [c.value for c in context_timeframes(Timeframe(tf))] for tf in TIMEFRAMES
        },
        "universe": list(UNIVERSE),
        "cost_model": asdict(cost),
        "entry_model": "retrace: limit at the confirmation-candle midpoint (cost floor kept)",
        "stop_model": "A: structure anchors + max(3 ticks, 0.1 ATR) buffer",
        "target_model": "A structural targets; runner exit 1/2 at TP1, 1/2 at TP3, 96-bar hold",
        "criteria": asdict(CRITERIA),
        "protocol": PROTOCOL,
    }


def _digest(config: dict[str, Any]) -> str:
    raw = json.dumps(config, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:10]


def forward_version(config: dict[str, Any] | None = None) -> str:
    return f"{FORWARD_VERSION_PREFIX}-{_digest(config or frozen_config())}"


def fingerprint(version: str) -> str:
    """Short display form, e.g. `4.2-1a2b3c4`."""
    return f"4.2-{version.rsplit('-', 1)[-1][:7]}"
