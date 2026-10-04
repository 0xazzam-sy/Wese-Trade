"""SignalEngine: the ONE canonical, pure signal evaluation.

    evaluation = SignalEngine(config).evaluate(SignalInput(snapshot, recent_bars, tick))

Flow: eligibility gate -> triggers -> setup families per side -> components ->
penalties -> score per hypothesis -> best bull / best bear (independent) -> class ->
trade plan -> NEUTRAL with an explicit reason whenever anything is missing or weak.

No state, no I/O, no wall clock: identical inputs give identical outputs, so live,
replay, backtest and scanner all agree. Cooldown, dedupe and lifecycle live in
lifecycle.SignalTracker.
"""

from __future__ import annotations

from typing import Any

from app.analysis.models import AnalysisSnapshot
from app.signal_engine.config import DEFAULT_SIGNAL_CONFIG, SignalConfig, strategy_version
from app.signal_engine.enums import SetupFamily, Side, SignalClass
from app.signal_engine.models import Hypothesis, SignalEvaluation, SignalInput, TradePlan
from app.signal_engine.rules import Setup, evaluate_setups, triggers
from app.signal_engine.scoring import (
    Ctx,
    Scored,
    apply_penalties,
    finalize,
    score_htf,
    score_liquidity,
    score_location,
    score_momentum,
    score_structure,
    score_trend,
    score_trigger_cluster,
)
from app.signal_engine.trade_plan import PlanRejectedError, build_plan

NEUTRAL_TEXT = {
    "not_ready": "التحليل غير جاهز",
    "stale": "بيانات السوق متأخرة",
    "inactive": "الرمز غير متاح للتداول",
    "volatility": "تذبذب مفرط — لا إشارات",
    "no_htf": "سياق الإطار الأعلى غير متاح",
    "inconsistent": "بيانات الهيكل غير متسقة",
    "no_trigger": "لا توجد فرصة واضحة",
    "no_setup": "لا يوجد إعداد مؤهل",
    "weak": "الأدلة ضعيفة — لا توجد فرصة واضحة",
    "conflicted": "أدلة متعارضة بين الشراء والبيع",
}


class SignalEngine:
    def __init__(self, config: SignalConfig = DEFAULT_SIGNAL_CONFIG) -> None:
        self.config = config
        self.version = strategy_version(config)

    # --- public -------------------------------------------------------------------------
    def evaluate(self, inp: SignalInput) -> SignalEvaluation:
        snap = inp.snapshot
        gate = self._gate(inp)
        if gate is not None:
            return self._neutral(snap, inp.developing, gate)
        best: dict[Side, tuple[Hypothesis, Setup] | None] = {Side.LONG: None, Side.SHORT: None}
        rejected: list[str] = []
        any_trigger = False
        for side in (Side.LONG, Side.SHORT):
            ctx = Ctx(snap, side, inp.recent_bars, inp.tick_size, self.config)
            for trig in triggers(ctx, inp.developing):
                any_trigger = True
                setups, why = evaluate_setups(ctx, trig)
                rejected += why
                for setup in setups:
                    if setup.family.value not in self.config.enabled_families:
                        continue
                    hyp = self._score(ctx, setup)
                    current = best[side]
                    if current is None or hyp.score > current[0].score:
                        best[side] = (hyp, setup)
        if not any_trigger:
            return self._neutral(snap, inp.developing, NEUTRAL_TEXT["no_trigger"])
        bull = best[Side.LONG]
        bear = best[Side.SHORT]
        if bull is None and bear is None:
            reason = rejected[0] if rejected else NEUTRAL_TEXT["no_setup"]
            return self._neutral(snap, inp.developing, reason)
        return self.classify(snap, inp, bull, bear)

    def classify(
        self,
        snap: AnalysisSnapshot,
        inp: SignalInput,
        bull: tuple[Hypothesis, Setup] | None,
        bear: tuple[Hypothesis, Setup] | None,
    ) -> SignalEvaluation:
        cfg = self.config
        bull_score = bull[0].score if bull else 0.0
        bear_score = bear[0].score if bear else 0.0
        regular, strong = cfg.threshold_for(snap.timeframe)
        chosen = bull if bull is not None and (bear is None or bull_score >= bear_score) else bear
        if chosen is None:  # pragma: no cover - evaluate() never calls with both None
            return self._neutral(snap, inp.developing, NEUTRAL_TEXT["no_setup"])
        hyp, setup = chosen
        top, other = max(bull_score, bear_score), min(bull_score, bear_score)
        neutral: str | None = None
        plan: TradePlan | None = None
        if top < regular:
            neutral = NEUTRAL_TEXT["weak"]
        elif top - other < cfg.min_score_spread:
            neutral = NEUTRAL_TEXT["conflicted"]
        if hyp.score >= cfg.evaluation_floor:
            try:
                plan = build_plan(Ctx(snap, hyp.side, inp.recent_bars, inp.tick_size, cfg), setup)
            except PlanRejectedError as exc:
                neutral = neutral or exc.reason
        if neutral is None and plan is None:
            neutral = NEUTRAL_TEXT["no_setup"]
        if neutral is not None:
            signal_class = SignalClass.NEUTRAL
        elif cfg.strong_enabled and top >= strong:
            signal_class = (
                SignalClass.STRONG_BUY if hyp.side is Side.LONG else SignalClass.STRONG_SELL
            )
        else:
            signal_class = SignalClass.BUY if hyp.side is Side.LONG else SignalClass.SELL
        return SignalEvaluation(
            symbol=snap.symbol,
            timeframe=snap.timeframe,
            candle_time=snap.forming_time if inp.developing else snap.candle_time,
            developing=inp.developing,
            signal_class=signal_class,
            side=hyp.side if signal_class is not SignalClass.NEUTRAL else None,
            score=hyp.score,
            bull_score=bull_score,
            bear_score=bear_score,
            hypothesis=hyp,
            best_bull=bull[0] if bull else None,
            best_bear=bear[0] if bear else None,
            plan=plan,
            neutral_reason=neutral,
            strategy_version=self.version,
            evidence=evidence(snap, hyp),
        )

    # --- internals ---------------------------------------------------------------------------
    def _gate(self, inp: SignalInput) -> str | None:
        snap = inp.snapshot
        if not snap.analysis_ready:
            return NEUTRAL_TEXT["not_ready"]
        if inp.market_stale:
            return NEUTRAL_TEXT["stale"]
        if not inp.symbol_active:
            return NEUTRAL_TEXT["inactive"]
        vol = snap.volatility
        if vol is not None and (vol.atr_percentile or 0) >= self.config.block_atr_percentile:
            return NEUTRAL_TEXT["volatility"]
        mtf = snap.multi_timeframe
        if (
            self.config.require_htf_context
            and mtf is not None
            and mtf.higher
            and not mtf.higher[0].ready
        ):
            return NEUTRAL_TEXT["no_htf"]
        swing = snap.swing_structure
        if swing is None:
            return NEUTRAL_TEXT["inconsistent"]
        if swing.direction.value == "bullish" and swing.protected_low is None:
            return NEUTRAL_TEXT["inconsistent"]
        if swing.direction.value == "bearish" and swing.protected_high is None:
            return NEUTRAL_TEXT["inconsistent"]
        return None

    def _score(self, ctx: Ctx, setup: Setup) -> Hypothesis:
        out = Scored([], [], [], [])
        out.positive.append(_trigger_reason(setup))
        score_htf(ctx, out)
        score_structure(ctx, out, setup.family)
        score_liquidity(ctx, out, setup.family)
        score_location(ctx, out, setup.family)
        score_trend(ctx, out)
        score_trigger_cluster(ctx, out, setup.trigger)
        score_momentum(ctx, out)
        apply_penalties(ctx, out, setup.family, setup.trigger)
        base, final = finalize(out)
        regime = ctx.snap.regime.directional.value if ctx.snap.regime else None
        return Hypothesis(
            family=setup.family,
            side=setup.side,
            trigger=setup.trigger,
            components=tuple(out.components),
            penalties=tuple(out.penalties),
            base_score=base,
            score=final,
            positive=tuple(dict.fromkeys(out.positive)),
            negative=tuple(dict.fromkeys(out.negative)),
            regime=regime,
        )

    def _neutral(self, snap: AnalysisSnapshot, developing: bool, reason: str) -> SignalEvaluation:
        return SignalEvaluation(
            symbol=snap.symbol,
            timeframe=snap.timeframe,
            candle_time=snap.forming_time if developing else snap.candle_time,
            developing=developing,
            signal_class=SignalClass.NEUTRAL,
            side=None,
            score=0.0,
            bull_score=0.0,
            bear_score=0.0,
            hypothesis=None,
            best_bull=None,
            best_bear=None,
            plan=None,
            neutral_reason=reason,
            strategy_version=self.version,
        )


def _trigger_reason(setup: Setup) -> str:
    from app.signal_engine import reasons as r

    event = r.structure_event(setup.trigger.layer, setup.trigger.type, setup.side)
    return f"{r.FAMILY_AR[setup.family]}: {event}"


def evidence(snap: AnalysisSnapshot, hyp: Hypothesis) -> dict[str, Any]:
    """Compact audit evidence: the facts the decision used (not the whole snapshot)."""
    mtf = snap.multi_timeframe
    pd = snap.premium_discount
    return {
        "candle_time": snap.candle_time,
        "price": snap.price,
        "trigger": {
            "id": hyp.trigger.id,
            "layer": hyp.trigger.layer,
            "type": hyp.trigger.type,
            "level": hyp.trigger.level,
            "displacement": hyp.trigger.displacement,
            "relative_volume": hyp.trigger.relative_volume,
        },
        "trend": snap.trend.direction.value if snap.trend else None,
        "trend_score": snap.trend.score if snap.trend else None,
        "regime": snap.regime.directional.value if snap.regime else None,
        "volatility": snap.volatility.regime.value if snap.volatility else None,
        "atr": snap.volatility.atr if snap.volatility else None,
        "atr_percentile": snap.volatility.atr_percentile if snap.volatility else None,
        "rsi": snap.momentum.rsi if snap.momentum else None,
        "swing": snap.swing_structure.direction.value if snap.swing_structure else None,
        "internal": snap.internal_structure.direction.value if snap.internal_structure else None,
        "premium_discount": None
        if pd is None
        else {"zone": pd.zone.value, "position": pd.position},
        "ote_in_zone": bool(snap.ote and snap.ote.price_in_zone),
        "mtf": None
        if mtf is None
        else {
            "alignment": mtf.directional_alignment.value,
            "frames": [
                {"tf": f.timeframe, "trend": f.trend.value if f.trend else None, "ready": f.ready}
                for f in mtf.higher
            ],
        },
        "family": hyp.family.value,
    }


__all__ = ["SetupFamily", "SignalEngine"]
