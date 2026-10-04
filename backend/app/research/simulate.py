"""Research pass 2: research variants over recorded hypotheses, canonical SignalTracker.

A `Variant` is a small, named, versioned strategy definition. It can only:
* restrict families / regimes / named feature filters,
* change the score model (category re-weighting of RECORDED component values),
* change threshold / spread,
* pick one of the pre-built plan models (entry / stop / target), a runner exit split,
  break-even after TP1,
* change the cost scenario.
It cannot change analysis or how plans are built; those come verbatim from pass 1.

Selection mirrors `SignalEngine.evaluate/classify` exactly (side loop order, strict ">" for
the best hypothesis per side, bull wins ties, plan rejection -> no trade), so the
`BASELINE` variant reproduces the frozen Phase 4 trades (tested).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, replace
from typing import Any

from app.analysis.series import Bar
from app.market_data.timeframes import Timeframe
from app.research.collect import ALL_FAMILIES, HypRecord, SeriesResearch, TriggerRecord
from app.signal_engine.config import DEFAULT_SIGNAL_CONFIG, SignalConfig, strategy_version
from app.signal_engine.enums import EntryModel, Side, SignalClass
from app.signal_engine.lifecycle import SignalTracker
from app.signal_engine.models import Hypothesis, Signal, SignalEvaluation, Target, TradePlan

BASELINE_VERSION = strategy_version(DEFAULT_SIGNAL_CONFIG)
RESEARCH_VERSION = "4.1"


# --- cost scenarios ---------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class CostScenario:
    name: str
    fee_rate: float  # taker, per side
    maker_fee_rate: float
    slippage_rate: float


COSTS = {
    # favourable but plausible: VIP-tier taker, small maker, tight spread on liquid perps
    "low": CostScenario("low", 0.0004, 0.0001, 0.0001),
    # Phase 4 assumptions (unchanged)
    "base": CostScenario("base", 0.0005, 0.0002, 0.0002),
    # stress: worse fees and 2.5x slippage (thin books, fast markets)
    "high": CostScenario("high", 0.0006, 0.0003, 0.0005),
}


# --- score models -------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ScoreModel:
    """Category weights over recorded component values (0..1) + penalty scale.

    `weights=None` keeps the recorded engine score (baseline). Components missing on a
    hypothesis (e.g. no higher timeframe on 1h) are excluded from normalization, exactly
    like the engine.
    """

    name: str
    weights: tuple[tuple[str, float], ...] | None = None
    penalty_scale: float = 1.0
    penalty_codes: tuple[str, ...] | None = None  # None = all recorded penalties count

    def score(self, hyp: Hypothesis) -> float:
        if self.weights is None:
            return hyp.score
        w = dict(self.weights)
        points = available = 0.0
        for c in hyp.components:
            weight = w.get(c.name, 0.0)
            if weight > 0:
                points += weight * c.value
                available += weight
        base = 100 * points / available if available else 0.0
        pens = sum(
            p.points
            for p in hyp.penalties
            if self.penalty_codes is None or p.code in self.penalty_codes
        )
        return max(0.0, min(100.0, base - self.penalty_scale * pens))


BASELINE_SCORE = ScoreModel("baseline")


# --- filters ----------------------------------------------------------------------------
Filter = Callable[[HypRecord], bool]
FILTERS: dict[str, Filter] = {
    "htf_aligned": lambda h: (
        h.features.get("htf_frames", 0) == 0
        or (h.features.get("htf1_trend") == 1 and h.features.get("htf1_structure") != -1)
    ),
    "htf_not_opposed": lambda h: h.features.get("htf1_trend") != -1,
    "swing_aligned": lambda h: h.features.get("swing") == 1,
    "trend_aligned": lambda h: h.features.get("trend_dir") == 1,
    "not_extended": lambda h: (h.features.get("ema_dist_atr") or 0.0) <= 2.0,
    "discount_half": lambda h: h.features.get("pd_pos") is not None and h.features["pd_pos"] <= 50,
    "vol_normal": lambda h: h.features.get("vol_regime") in ("normal", "low", "compressed"),
    "has_zone": lambda h: isinstance(h.plans.get("zone/A/A"), TradePlan),
    "displacement_relvol": lambda h: (
        (h.features.get("displacement") or 0) >= 50 and (h.features.get("relvol") or 0) >= 1.2
    ),
}


@dataclass(frozen=True, slots=True)
class Variant:
    name: str
    families: tuple[str, ...] = ALL_FAMILIES
    score: ScoreModel = BASELINE_SCORE
    threshold: float = 75.0
    spread: float = 10.0
    excluded_regimes: tuple[str, ...] = ()
    filters: tuple[str, ...] = ()
    entry: str = "base"  # base | close | zone | retrace
    stop: str = "A"
    target: str = "A"
    runner: bool = False
    break_even: bool = False
    costs: str = "base"
    notes: str = ""

    def plan_key(self) -> str:
        entry = "close" if self.entry == "retrace" else self.entry
        if entry != "base" and (self.stop, self.target) != ("A", "A"):
            raise ValueError("entry models are only combined with stop A / target A")
        return f"{entry}/{self.stop}/{self.target}"

    def definition(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("name")
        data.pop("notes")
        return data

    @property
    def version(self) -> str:
        if self.definition() == Variant("baseline").definition():
            return BASELINE_VERSION
        raw = json.dumps(
            {"base": BASELINE_VERSION, "research": RESEARCH_VERSION, "variant": self.definition()},
            sort_keys=True,
            default=str,
        )
        digest = hashlib.sha256(raw.encode()).hexdigest()[:10]
        return f"wese-trade-research-{RESEARCH_VERSION}-{digest}"

    def tracker_config(self) -> SignalConfig:
        cost = COSTS[self.costs]
        changes: dict[str, Any] = {
            "fee_rate": cost.fee_rate,
            "maker_fee_rate": cost.maker_fee_rate,
            "slippage_rate": cost.slippage_rate,
            "move_stop_to_entry_after_tp1": self.break_even,
        }
        if self.runner:
            changes["target_fractions"] = (0.5, 0.0, 0.5)
            changes["max_hold_bars"] = 96
        return DEFAULT_SIGNAL_CONFIG.with_changes(**changes)


BASELINE = Variant("baseline", notes="frozen Phase 4 strategy wese-trade-signal-4.0-f26f636443")


# --- selection ------------------------------------------------------------------------------
@dataclass(slots=True)
class Pick:
    record: HypRecord
    score: float


def eligible(v: Variant, h: HypRecord) -> bool:
    if h.family not in v.families:
        return False
    if v.excluded_regimes and h.features.get("regime") in v.excluded_regimes:
        return False
    return all(FILTERS[f](h) for f in v.filters)


def select(v: Variant, trig: TriggerRecord) -> tuple[Pick | None, Pick | None]:
    best: dict[str, Pick | None] = {"long": None, "short": None}
    for h in trig.hyps:
        if not eligible(v, h):
            continue
        sc = v.score.score(h.hyp)
        cur = best[h.side]
        if cur is None or sc > cur.score:
            best[h.side] = Pick(h, sc)
    return best["long"], best["short"]


def retrace_plan(plan: TradePlan, bar: Bar, tick: float, cfg: SignalConfig) -> TradePlan:
    """Limit at the confirmation candle's midpoint (never beyond the cost/ATR risk floor)."""
    sign = 1 if plan.stop < plan.preferred_entry else -1
    atr = plan.risk / plan.risk_atr if plan.risk_atr else plan.risk
    floor = max(
        cfg.min_stop_atr * atr,
        cfg.min_stop_ticks * tick,
        cfg.min_risk_cost_multiple * cfg.round_trip_cost_rate() * plan.preferred_entry,
    )
    mid = (bar.high + bar.low) / 2
    entry = plan.preferred_entry
    if sign > 0:
        # better than the close, never closer to the stop than the risk floor, never worse
        limit = min(max(min(mid, entry), plan.stop + floor), entry)
    else:
        limit = max(min(max(mid, entry), plan.stop - floor), entry)
    if tick > 0:
        limit = round(round(limit / tick) * tick, 12)
    risk = sign * (limit - plan.stop)
    targets = tuple(
        Target(t.price, round(sign * (t.price - limit) / risk, 2), t.source) for t in plan.targets
    )
    return replace(
        plan,
        entry_model=EntryModel.ZONE,
        entry_low=min(limit, plan.preferred_entry),
        entry_high=max(limit, plan.preferred_entry),
        preferred_entry=limit,
        risk=risk,
        risk_atr=round(risk / atr, 3) if atr else plan.risk_atr,
        targets=targets,  # type: ignore[arg-type]
    )


def evaluation(v: Variant, series: SeriesResearch, trig: TriggerRecord) -> SignalEvaluation | None:
    bull, bear = select(v, trig)
    if trig.gated is not None or (bull is None and bear is None):
        return None
    bull_s = bull.score if bull else 0.0
    bear_s = bear.score if bear else 0.0
    chosen = bull if bull is not None and (bear is None or bull_s >= bear_s) else bear
    if chosen is None:  # pragma: no cover - excluded above
        return None
    top, other = max(bull_s, bear_s), min(bull_s, bear_s)
    if top < v.threshold or top - other < v.spread:
        return None
    plan = chosen.record.plans.get(v.plan_key())
    if not isinstance(plan, TradePlan):
        return None
    if v.entry == "retrace":
        plan = retrace_plan(plan, series.bars[trig.index], series.tick, DEFAULT_SIGNAL_CONFIG)
    side = Side(chosen.record.side)
    rescored = v.score.weights is not None
    hyp = (
        replace(chosen.record.hyp, score=round(chosen.score, 2)) if rescored else chosen.record.hyp
    )
    score = hyp.score
    return SignalEvaluation(
        symbol=series.symbol,
        timeframe=series.timeframe,
        candle_time=trig.baseline.candle_time,
        developing=False,
        signal_class=SignalClass.BUY if side is Side.LONG else SignalClass.SELL,
        side=side,
        score=score,
        bull_score=bull_s,
        bear_score=bear_s,
        hypothesis=hyp,
        best_bull=bull.record.hyp if bull else None,
        best_bear=bear.record.hyp if bear else None,
        plan=plan,
        neutral_reason=None,
        strategy_version=v.version,
        evidence={"features": chosen.record.features},
    )


def run(v: Variant, series: SeriesResearch) -> list[Signal]:
    """Canonical SignalTracker over the series with this variant's selections."""
    tracker = SignalTracker(
        series.symbol,
        series.timeframe,
        v.tracker_config(),
        step_seconds=Timeframe(series.timeframe).seconds,
    )
    by_index = {t.index: t for t in series.triggers}
    for bar in series.bars:
        tracker.on_bar(bar)
        trig = by_index.get(bar.index)
        if trig is None:
            continue
        ev = evaluation(v, series, trig)
        if ev is not None:
            tracker.on_evaluation(ev, bar)
    if series.bars:
        tracker.finish_open(series.bars[-1].close_time, series.bars[-1].close)
    return tracker.closed


@dataclass(slots=True)
class Outcome:
    """One hypothesis traded in isolation (no cooldown/overlap rules): score research."""

    symbol: str
    timeframe: str
    time: int
    family: str
    side: str
    score: float
    features: dict[str, Any]
    components: dict[str, float]
    penalties: dict[str, float]
    entered: bool
    net_r: float | None
    gross_r: float | None
    risk_atr: float
    cost_r: float | None = field(default=None)


def isolated_outcomes(
    series: SeriesResearch,
    *,
    plan_key: str = "base/A/A",
    families: Iterable[str] = ALL_FAMILIES,
    min_score: float = 0.0,
) -> list[Outcome]:
    cfg = DEFAULT_SIGNAL_CONFIG
    step = Timeframe(series.timeframe).seconds
    horizon = cfg.entry_expiry_bars + cfg.max_hold_bars + 2
    allowed = set(families)
    out: list[Outcome] = []
    for trig in series.triggers:
        for h in trig.hyps:
            plan = h.plans.get(plan_key)
            if (
                h.family not in allowed
                or not isinstance(plan, TradePlan)
                or h.hyp.score < min_score
            ):
                continue
            side = Side(h.side)
            ev = SignalEvaluation(
                series.symbol,
                series.timeframe,
                trig.baseline.candle_time,
                False,
                SignalClass.BUY if side is Side.LONG else SignalClass.SELL,
                side,
                h.hyp.score,
                0.0,
                0.0,
                h.hyp,
                None,
                None,
                plan,
                None,
                "isolated",
            )
            tracker = SignalTracker(series.symbol, series.timeframe, cfg, step_seconds=step)
            bar = series.bars[trig.index]
            sig = tracker.on_evaluation(ev, bar)
            if sig is None:
                continue
            for b in series.bars[trig.index + 1 : trig.index + 1 + horizon]:
                tracker.on_bar(b)
                if tracker.active is None:
                    break
            if tracker.active is not None:
                last = series.bars[min(len(series.bars) - 1, trig.index + horizon)]
                tracker.finish_open(last.close_time, last.close)
            s = tracker.closed[-1]
            out.append(
                Outcome(
                    series.symbol,
                    series.timeframe,
                    bar.close_time,
                    h.family,
                    h.side,
                    h.hyp.score,
                    h.features,
                    {c.name: c.value for c in h.hyp.components},
                    {p.code: p.points for p in h.hyp.penalties},
                    s.entered,
                    s.net_r,
                    s.gross_r,
                    plan.risk_atr,
                    None if s.net_r is None or s.gross_r is None else s.gross_r - s.net_r,
                )
            )
    return out
