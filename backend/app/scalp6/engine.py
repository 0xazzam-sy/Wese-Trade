"""wese-trade-scalp-6: weighted-confluence fast-trading engine (1m / 5m / 10m).

docs/research-scalp6.md. One incremental engine, fed CLOSED candles only, used by both the
research replay and the live service. Decisions are BUY / SELL / NEUTRAL with an a-priori
weighted confluence score («قوة الإشارة», not a probability of winning), a structural plan
(entry, stop, TP1-3, R:R) and real reasons. Strategy 4.2 (15m/30m/1h) is a different engine.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from app.scalp6.indicators import Atr, Ema, RollingMean, RollingPercentile, Rsi
from app.scalp6.levels import Level, LevelBook
from app.scalp6.structure import StructureTracker

WARMUP = 200
MAX_GAP = 3
FRICTION = 2 * 0.0005 + 2 * 0.0002 + 0.0002  # taker + slippage both sides + stop extra
FRICTION_MAX = 0.25  # friction must stay <= 25% of risk (hard blocker)
MARGIN = 10.0
COMPONENTS = ("trend", "ema", "structure", "sr", "liquidity", "momentum", "volume", "candle", "htf")

# A-priori family weights (fixed before research; not fitted).
WEIGHTS: dict[str, dict[str, float]] = {
    "A": {"trend": 3, "ema": 2, "structure": 2, "htf": 2, "momentum": 1, "sr": 1,
          "liquidity": 0.5, "volume": 0.5, "candle": 1},
    "B": {"momentum": 3, "volume": 2, "candle": 2, "structure": 1.5, "trend": 1, "htf": 1,
          "sr": 1, "ema": 0.5, "liquidity": 0.5},
    "C": {"sr": 3, "liquidity": 3, "candle": 2, "momentum": 1.5, "structure": 1, "volume": 1,
          "htf": 0.5, "trend": 0.5, "ema": 0.5},
}  # fmt: skip
FAMILY_AR = {
    "A": "استمرار الاتجاه",
    "B": "اختراق بزخم",
    "C": "سحب سيولة وانعكاس",
}
REGIME_AR = {"trending": "اتجاهي", "ranging": "عرضي", "transitional": "انتقالي"}


@dataclass(frozen=True, slots=True)
class Profile:
    timeframe: str
    ema: tuple[int, int, int] = (9, 21, 50)
    fractal: int = 2
    families: tuple[str, ...] = ("A", "B", "C")
    adaptive: bool = True
    threshold: float = 70.0
    entry: str = "market"  # market | limit

    def key(self) -> str:
        fam = "D" if self.adaptive else "+".join(self.families)
        e = "/".join(map(str, self.ema))
        return f"ema={e} fam={fam} T={self.threshold:g} entry={self.entry}"


@dataclass(frozen=True, slots=True)
class TradePlan:
    side: int
    entry: float  # the actionable entry price
    entry_mode: str  # market | limit
    market_entry: float  # signal close (for comparison / missed-entry checks)
    stop: float
    targets: tuple[float, float, float]
    target_sources: tuple[str, str, str]

    @property
    def risk(self) -> float:
        return self.side * (self.entry - self.stop)

    @property
    def rr(self) -> tuple[float, float, float]:
        r = self.risk
        return tuple(round(self.side * (t - self.entry) / r, 2) for t in self.targets)  # type: ignore[return-value]


@dataclass(slots=True)
class Decision:
    index: int
    time: int  # signal candle CLOSE time (ms)
    side: int  # +1 BUY, -1 SELL, 0 NEUTRAL
    family: str | None
    score: float
    score_long: float
    score_short: float
    components: dict[str, float]
    plan: TradePlan | None
    reasons: list[str]
    blockers: list[str]
    regime: str
    direction: int
    triggered: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Evaluation:
    """One triggered family/side on the closed candle (before profile selection)."""

    family: str
    side: int
    score: float  # raw family score (no regime penalty)
    market: TradePlan
    limit: TradePlan | None
    blockers: tuple[str, ...]  # structural blockers (not score)


@dataclass
class ContextTrend:
    """Direction of one higher timeframe from its CLOSED candles."""

    fast: Ema = field(default_factory=lambda: Ema(20))
    slow: Ema = field(default_factory=lambda: Ema(50))
    atr: Atr = field(default_factory=Atr)
    count: int = 0
    last_close: float = 0.0

    def update(self, h: float, lo: float, c: float) -> None:
        self.fast.update(c)
        self.slow.update(c)
        self.atr.update(h, lo, c)
        self.count += 1
        self.last_close = c

    def direction(self) -> tuple[int, float]:
        f, s, a = self.fast.value, self.slow.value, self.atr.value
        if self.count < 60 or f is None or s is None or not a:
            return 0, 0.0
        strength = min(1.0, abs(f - s) / a)
        slope = self.slow.slope()
        if f > s and slope > 0 and self.last_close > s:
            return 1, strength
        if f < s and slope < 0 and self.last_close < s:
            return -1, strength
        return 0, strength


def allowed_families(p: Profile, regime: str) -> tuple[str, ...]:
    """Regime-adaptive routing (architecture D) or a fixed family set (A / B / C)."""
    if not p.adaptive:
        return p.families
    if regime == "trending":
        return ("A", "B")
    if regime == "ranging":
        return ("B", "C")
    return ("A", "B", "C")


def choose(
    evals: list[Evaluation], regime: str, p: Profile
) -> tuple[Evaluation, float, TradePlan, list[str]] | None:
    """Pure profile selection: best allowed evaluation, its score, plan and blockers."""
    allowed = allowed_families(p, regime)
    pool = [e for e in evals if e.family in allowed]
    if not pool:
        return None
    best = max(pool, key=lambda e: e.score)
    penalty = 10.0 if p.adaptive and regime == "transitional" else 0.0
    score = round(best.score - penalty, 1)
    opposite = round(100 - best.score, 1)
    plan = best.limit if p.entry == "limit" and best.limit is not None else best.market
    blockers = list(best.blockers)
    if score < p.threshold:
        blockers.append("score_below_threshold")
    if score - opposite < MARGIN:
        blockers.append("conflicted")
    return best, score, plan, blockers


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


class Scalp6Engine:
    """Feed closed candles with `update`; read `decision` / analysis attributes after each."""

    def __init__(self, profile: Profile, step_ms: int) -> None:
        self.p = profile
        self.step = step_ms
        f, m, s = profile.ema
        self.ema_f, self.ema_m, self.ema_s = Ema(f), Ema(m), Ema(s)
        self.atr = Atr(14)
        self.rsi = Rsi(14)
        self.atr_pct = RollingPercentile(300)
        self.vol_mean = RollingMean(20)
        self.structure = StructureTracker(profile.fractal)
        self.major = StructureTracker(profile.fractal * 2)
        self.levels = LevelBook()
        self.i = -1
        self.warm = 0
        self.last_t: int | None = None
        self.closes: deque[float] = deque(maxlen=8)
        self.highs: deque[float] = deque(maxlen=10)
        self.lows: deque[float] = deque(maxlen=10)
        self.ef_hist: deque[float] = deque(maxlen=6)
        self.pct_hist: deque[float] = deque(maxlen=20)
        self.last_trigger: dict[tuple[str, int], int] = {}
        self.evals: list[Evaluation] = []
        self.decision: Decision | None = None
        self.context: list[tuple[int, float]] = []
        # latest analysis values (live display)
        self.o = self.h = self.lo = self.c = self.v = 0.0
        self.rel_vol = 1.0
        self.pct = 50.0
        self.regime = "transitional"
        self.direction = 0
        self.direction_score = 0.0
        self.long_components: dict[str, float] = {}

    # ------------------------------------------------------------------ update
    def update(
        self,
        t: int,
        o: float,
        h: float,
        lo: float,
        c: float,
        v: float,
        context: list[tuple[int, float]] | None = None,
    ) -> Decision:
        self.i += 1
        i = self.i
        if self.last_t is not None and t - self.last_t > (MAX_GAP + 1) * self.step:
            self._restart()
        self.last_t = t
        self.warm += 1
        prev_c = self.closes[-1] if self.closes else c
        atr = self.atr.update(h, lo, c)
        ef, em, es = self.ema_f.update(c), self.ema_m.update(c), self.ema_s.update(c)
        self.rsi.update(c)
        self.pct = self.atr_pct.update(atr)
        mean_v = self.vol_mean.mean
        self.rel_vol = v / mean_v if mean_v > 0 else 1.0
        self.vol_mean.update(v)
        for sw in self.structure.update(i, t, h, lo, c, atr):
            self.levels.seed(sw.price, i, self.rel_vol, atr)
        self.major.update(i, t, h, lo, c, atr)
        self.levels.update(i, h, lo, c, prev_c, atr)
        self.o, self.h, self.lo, self.c, self.v = o, h, lo, c, v
        self.closes.append(c)
        self.highs.append(h)
        self.lows.append(lo)
        self.ef_hist.append(ef)
        self.pct_hist.append(self.pct)
        self.context = context or []
        self.long_components = self._components(atr, ef, em, es)
        self.regime = self._regime(atr, ef, em, es)
        self._direction()
        self.decision = self._decide(i, t + self.step, atr, ef)
        return self.decision

    def _restart(self) -> None:
        self.warm = 0
        self.structure.reset()
        self.major.reset()
        self.levels.reset()
        self.closes.clear()
        self.highs.clear()
        self.lows.clear()
        self.ef_hist.clear()
        self.pct_hist.clear()

    # -------------------------------------------------------------- analysis
    def _components(self, atr: float, ef: float, em: float, es: float) -> dict[str, float]:
        c, o, h, lo = self.c, self.o, self.h, self.lo
        if not atr:
            return dict.fromkeys(COMPONENTS, 0.0)
        order = 1.0 if ef > em > es else -1.0 if ef < em < es else 0.5 * (1 if ef > es else -1)
        slope = _clip(self.ema_m.slope() / (0.5 * atr))
        trend = 0.6 * order + 0.4 * slope
        dist = (c - em) / atr
        if abs(dist) <= 3:
            ema = _clip(dist / 0.5)
        else:  # over-extended from the mean: weaker evidence
            ema = _clip((1 if dist > 0 else -1) * (1 - (abs(dist) - 3) / 2))
        st = self.structure
        ev = st.last_event()
        recent = 0.0
        if ev is not None and self.i - ev.index <= 10:
            recent = float(ev.direction) * (1.0 if ev.kind == "CHOCH" else 0.6)
        structure = _clip(0.7 * st.direction + 0.3 * recent)
        sr = 0.0
        for lv in self.levels.nearest(c, above=False, i=self.i, min_grade="medium")[:1]:
            d = (c - lv.price) / atr
            if d <= 1.5:
                sr += (1 - d / 1.5) * (1.0 if lv.grade(self.i) == "strong" else 0.6)
        for lv in self.levels.nearest(c, above=True, i=self.i, min_grade="medium")[:1]:
            d = (lv.price - c) / atr
            if d <= 1.5:
                sr -= (1 - d / 1.5) * (1.0 if lv.grade(self.i) == "strong" else 0.6)
        liquidity = 0.0
        if st.last_sweep is not None:
            age = self.i - st.last_sweep[0]
            if age <= 5:
                liquidity = st.last_sweep[1] * (1 - age / 6)
        roc = (c - self.closes[0]) / atr if len(self.closes) > 1 else 0.0
        rsi = self.rsi.value
        momentum = _clip(
            0.6 * _clip(roc / 2) + 0.2 * _clip((rsi - 50) / 25) + 0.2 * _clip(self.rsi.slope() / 10)
        )
        body = c - o
        rng = h - lo
        candle = _clip(body / atr) * (0.5 + 0.5 * (abs(body) / rng if rng > 0 else 0))
        volume = 0.0
        if self.rel_vol >= 1.2 and body != 0:
            volume = (1 if body > 0 else -1) * min(1.0, self.rel_vol - 1.0)
        htf = 0.0
        if self.context:
            htf = sum(d * (0.5 + 0.5 * s) for d, s in self.context) / len(self.context)
        return {
            "trend": trend,
            "ema": ema,
            "structure": structure,
            "sr": _clip(sr),
            "liquidity": liquidity,
            "momentum": momentum,
            "volume": volume,
            "candle": candle,
            "htf": htf,
        }

    def _regime(self, atr: float, ef: float, em: float, es: float) -> str:
        if not atr:
            return "transitional"
        spread = (ef - es) / atr
        slope = self.ema_m.slope()
        sd = self.structure.direction
        if abs(spread) >= 1.0 and spread * slope > 0 and sd == (1 if spread > 0 else -1):
            return "trending"
        if abs(spread) < 0.5 and self.pct < 80:
            return "ranging"
        return "transitional"

    def _direction(self) -> None:
        k = self.long_components
        s = 0.35 * k["trend"] + 0.3 * k["structure"] + 0.15 * k["momentum"] + 0.2 * k["htf"]
        self.direction_score = round(s, 3)
        self.direction = 1 if s > 0.3 else -1 if s < -0.3 else 0

    # -------------------------------------------------------------- triggers
    def _trigger_a(self, side: int, ef: float, atr: float) -> bool:
        k = self.long_components
        if side * k["trend"] <= 0 or len(self.ef_hist) < 6:
            return False
        lows, highs, efs = list(self.lows)[-5:], list(self.highs)[-5:], list(self.ef_hist)[-5:]
        if side == 1:
            touched = any(lv <= e + 0.1 * atr for lv, e in zip(lows, efs, strict=False))
            return touched and self.c > ef and self.c > self.o
        touched = any(hv >= e - 0.1 * atr for hv, e in zip(highs, efs, strict=False))
        return touched and self.c < ef and self.c < self.o

    def _trigger_b(self, side: int, atr: float) -> Level | None:
        if not self.pct_hist or min(self.pct_hist) > 30 or abs(self.c - self.o) < 0.6 * atr:
            return None
        if side * (self.c - self.o) <= 0 or len(self.closes) < 2:
            return None
        prev = self.closes[-2]
        for lv in self.levels.levels:
            if lv.grade(self.i) == "weak" or lv.breakout_used:
                continue
            p = lv.price
            if side == 1 and prev <= p < self.c - 0.1 * atr:
                return lv
            if side == -1 and prev >= p > self.c + 0.1 * atr:
                return lv
        return None

    def _trigger_c(self, side: int, atr: float) -> tuple[float, float] | None:
        """(reclaimed level, sweep extreme) if a sweep against `side` was just reclaimed."""
        sw = self.structure.last_sweep
        if (
            sw is not None
            and sw[1] == side
            and self.i - sw[0] <= 3
            and side * (self.c - sw[2]) > 0
            and side * (self.c - self.o) > 0
        ):
            return sw[2], sw[3]
        # sweep of a medium/strong S/R level (wick through, close back) on this candle
        for lv in self.levels.nearest(self.c, above=side == -1, i=self.i, min_grade="medium")[:2]:
            p = lv.price
            if side == 1 and self.lo < p - 0.1 * atr and self.c > p and self.c > self.o:
                return p, self.lo
            if side == -1 and self.h > p + 0.1 * atr and self.c < p and self.c < self.o:
                return p, self.h
        return None

    # -------------------------------------------------------------- decision
    def _score(self, family: str, side: int) -> float:
        w = WEIGHTS[family]
        k = self.long_components
        total = sum(w.values())
        mean = sum(w[name] * k[name] for name in w) / total
        return round(50 + 50 * side * mean, 1)

    def _decide(self, i: int, close_ms: int, atr: float, ef: float) -> Decision:
        blockers: list[str] = []
        d = Decision(
            i, close_ms, 0, None, 0.0, 0.0, 0.0, self.long_components, None, [], blockers,
            self.regime, self.direction,
        )  # fmt: skip
        self.evals = []
        if self.warm < WARMUP or not atr:
            blockers.append("warmup")
            return d
        if self.pct >= 99 or (self.h - self.lo) > 6 * atr:
            blockers.append("extreme_volatility")
            return d
        self.evals = self._evaluate_all(atr, ef)
        return self.select(d, self.evals, self.p)

    def select(self, d: Decision, evals: list[Evaluation], p: Profile) -> Decision:
        """Profile selection over the candle's evaluations."""
        d.triggered = tuple(f"{e.family}{'+' if e.side == 1 else '-'}" for e in evals)
        pick = choose(evals, self.regime, p)
        if pick is None:
            d.reasons = ["لا يوجد إعداد مكتمل حالياً"]
            return d
        best, score, plan, blockers = pick
        opposite = round(100 - best.score, 1)
        d.family, d.score, d.plan = best.family, score, plan
        d.score_long, d.score_short = (score, opposite) if best.side == 1 else (opposite, score)
        d.blockers.extend(blockers)
        if blockers:
            return d
        d.side = best.side
        d.reasons = self._reasons(best.family, best.side, plan)
        return d

    def _evaluate_all(self, atr: float, ef: float) -> list[Evaluation]:
        out = []
        for side in (1, -1):
            for fam in ("A", "B", "C"):
                plans = self._family_plan(fam, side, atr, ef)
                if plans is None:
                    continue
                market, limit = plans
                self.last_trigger[(fam, side)] = self.i
                b: list[str] = []
                risk = market.risk
                if risk <= 0 or risk > 4 * atr:
                    b.append("impossible_stop")
                elif market.rr[1] < 1.0:
                    b.append("poor_rr")
                elif FRICTION * market.entry > FRICTION_MAX * risk:
                    b.append("friction")
                out.append(Evaluation(fam, side, self._score(fam, side), market, limit, tuple(b)))
        return out

    def _family_plan(
        self, fam: str, side: int, atr: float, ef: float
    ) -> tuple[TradePlan, TradePlan | None] | None:
        c = self.c
        if self.i - self.last_trigger.get((fam, side), -100) < 5:
            return None  # the same setup cannot trigger again immediately
        if fam == "A":
            if not self._trigger_a(side, ef, atr):
                return None
            extreme = min(self.lows) if side == 1 else max(self.highs)
            stop = extreme - side * 0.2 * atr
            limit = ef
        elif fam == "B":
            lv = self._trigger_b(side, atr)
            if lv is None:
                return None
            lv.breakout_used = True
            stop = (
                min(lv.price - 0.3 * atr, self.lo)
                if side == 1
                else max(lv.price + 0.3 * atr, self.h)
            )
            limit = lv.price
        else:
            hit = self._trigger_c(side, atr)
            if hit is None:
                return None
            level, extreme = hit
            stop = extreme - side * 0.2 * atr
            limit = level
        market = self._plan(side, c, "market", stop, atr, c)
        lim = None
        if side * (c - limit) > 0.05 * atr and side * (limit - stop) > 0:
            lim = self._plan(side, limit, "limit", stop, atr, c)
        return market, lim

    def _plan(
        self, side: int, entry: float, mode: str, stop: float, atr: float, close: float
    ) -> TradePlan:
        if side * (entry - stop) < 0.5 * atr:
            stop = entry - side * 0.5 * atr
        risk = side * (entry - stop)
        targets, sources = self._targets(side, entry, risk, atr)
        return TradePlan(side, entry, mode, close, stop, targets, sources)

    def _targets(
        self, side: int, entry: float, risk: float, atr: float
    ) -> tuple[tuple[float, float, float], tuple[str, str, str]]:
        cands: list[tuple[float, str]] = []
        for lv in self.levels.levels:
            if side * (lv.price - entry) > 0:
                kind = "resistance" if side == 1 else "support"
                cands.append((lv.price - side * 0.05 * atr, f"{kind}:{lv.grade(self.i)}"))
        for pool in self.structure.active_pools(above=side == 1):
            if side * (pool.price - entry) > 0:
                cands.append((pool.price - side * 0.05 * atr, "liquidity"))
        cands.sort(key=lambda x: side * (x[0] - entry))
        out: list[float] = []
        src: list[str] = []
        floors = (0.8, 0.5, 0.5)
        fallback = (1.0, 2.0, 3.0)
        for k in range(3):
            base = entry if k == 0 else out[-1]
            need = base + side * floors[k] * risk
            pick = next(((p, s) for p, s in cands if side * (p - need) >= 0), None)
            # structure target, but never beyond 6R; else an R projection
            if pick is not None and side * (pick[0] - entry) <= 6 * risk:
                out.append(pick[0])
                src.append(pick[1])
            else:
                proj = entry + side * max(fallback[k], (side * (need - entry)) / risk) * risk
                out.append(proj)
                src.append("projection")
        return (out[0], out[1], out[2]), (src[0], src[1], src[2])

    # -------------------------------------------------------------- reasons
    def _reasons(self, fam: str, side: int, plan: TradePlan) -> list[str]:
        k = {name: side * v for name, v in self.long_components.items()}
        up = side == 1
        f, m, s = self.p.ema
        out = [FAMILY_AR[fam]]
        if k["trend"] > 0.3:
            out.append(
                f"الاتجاه {'صاعد' if up else 'هابط'} — ترتيب EMA {f}/{m}/{s} "
                f"{'صاعد' if up else 'هابط'}"
            )
        if k["ema"] > 0.3:
            out.append(f"السعر {'فوق' if up else 'تحت'} EMA {m}")
        ev = self.structure.last_event()
        if k["structure"] > 0.3 and ev is not None:
            name = "CHoCH" if ev.kind == "CHOCH" else "BOS"
            out.append(
                f"{name} {'صاعد' if up else 'هابط'} — الهيكل يدعم {'الشراء' if up else 'البيع'}"
            )
        if k["sr"] > 0.2:
            out.append(f"ارتداد من {'دعم' if up else 'مقاومة'} قريب")
        if k["liquidity"] > 0.2 and self.structure.last_sweep is not None:
            where = "أسفل القاع" if up else "أعلى القمة"
            out.append(f"تم سحب سيولة {where} عند {self.structure.last_sweep[2]:.6g}")
        if k["momentum"] > 0.3:
            out.append(f"الزخم {'الشرائي' if up else 'البيعي'} قوي (RSI {self.rsi.value:.0f})")
        if k["volume"] > 0.2:
            out.append(f"حجم التداول أعلى من المتوسط بـ {self.rel_vol:.1f} ضعف")
        if k["candle"] > 0.4:
            out.append(f"شمعة تأكيد {'صاعدة' if up else 'هابطة'} قوية")
        if k["htf"] > 0.3:
            out.append("الفريمات الأعلى داعمة")
        elif k["htf"] < -0.3:
            out.append("تنبيه: الفريمات الأعلى معاكسة")
        kind = "مقاومة" if up else "دعم"
        if plan.target_sources[0].startswith(("resistance", "support")):
            out.append(f"الهدف الأول عند {kind} {plan.targets[0]:.6g}")
        elif plan.target_sources[0] == "liquidity":
            out.append(f"الهدف الأول عند سيولة {'علوية' if up else 'سفلية'} {plan.targets[0]:.6g}")
        return out
