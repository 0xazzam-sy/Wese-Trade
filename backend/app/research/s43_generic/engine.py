"""Strategy 4.3 engine: one incremental evaluator per stream, fed CLOSED candles only.

The same object runs in the research replay and in the live scanner. Inputs are the
closed bar and the canonical MarketAnalyzer snapshot of that bar (structure, liquidity,
regime, zones, multi-timeframe context). Own incremental state: EMA 20/50/200, ATR, RSI,
relative volume, the scalp-6 support/resistance book with level strength, a 4x higher
timeframe aggregate and recent breakouts (for retests).

Decision:
    1. hard blockers (only genuinely unsafe cases)
    2. setup families detected on this candle (10 families, regime-weighted)
    3. weighted evidence -> BUY score and SELL score (0-100, confluence, not probability)
    4. side = the stronger side with a setup, a margin over the other side and a valid plan
    5. tier from calibrated score thresholds (A+ / A / B / C, else WAIT)
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import asdict, dataclass

from app.analysis.models import AnalysisSnapshot, StructureEvent
from app.analysis.series import Bar
from app.research.s43_generic.models import (
    FAMILY_AR,
    Evaluation,
    Family,
    Plan,
    Regime,
    Setup,
)
from app.scalp6.indicators import Atr, Ema, RollingMean, RollingPercentile, Rsi
from app.scalp6.levels import LevelBook
from app.scalp6.structure import StructureTracker

STRATEGY_NAME = "Wese Trade Strategy 4.3"
VERSION_PREFIX = "wese-trade-strategy-4.3"
WARMUP = 210


@dataclass(frozen=True, slots=True)
class Config:
    """Everything that determines a 4.3 decision (hashed into the version)."""

    weights: tuple[tuple[str, float], ...] = (
        ("trend", 16.0),
        ("structure", 14.0),
        ("mtf", 12.0),
        ("momentum", 10.0),
        ("volume", 6.0),
        ("location", 12.0),
        ("setup", 20.0),
        ("candle", 5.0),
        ("regime", 5.0),
    )
    # Tier thresholds on the chosen side's score (calibrated, docs/strategy-4.3.md).
    tier_c: float = 58.0
    tier_b: float = 64.0
    tier_a: float = 70.0
    tier_a_plus: float = 77.0
    margin: float = 8.0  # chosen side must lead the other side by this much
    # Plan geometry
    stop_buffer_atr: float = 0.2
    min_stop_atr: float = 0.7
    max_stop_atr: float = 3.5
    min_rr_tp1: float = 1.0
    min_rr_tp2: float = 1.5
    # Hard blockers
    catastrophic_range_atr: float = 6.0
    setup_lookback: int = 2  # a setup trigger stays valid for this many extra candles

    def weight(self, name: str) -> float:
        return dict(self.weights)[name]

    def tier(self, score: float) -> str:
        if score >= self.tier_a_plus:
            return "A+"
        if score >= self.tier_a:
            return "A"
        if score >= self.tier_b:
            return "B"
        if score >= self.tier_c:
            return "C"
        return "WAIT"


DEFAULT_CONFIG = Config()


def strategy_version(cfg: Config = DEFAULT_CONFIG) -> str:
    raw = json.dumps(asdict(cfg), sort_keys=True, default=str, separators=(",", ":"))
    return f"{VERSION_PREFIX}-{hashlib.sha256(raw.encode()).hexdigest()[:10]}"


def fingerprint(version: str) -> str:
    return f"4.3-{version.rsplit('-', 1)[-1][:7]}"


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


@dataclass(slots=True)
class _Breakout:
    index: int
    level: float
    side: int


class Strategy43:
    """Incremental 4.3 evaluator for one (symbol, timeframe) stream."""

    def __init__(
        self, symbol: str, timeframe: str, step_seconds: int, cfg: Config = DEFAULT_CONFIG
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.step = step_seconds
        self.cfg = cfg
        self.version = strategy_version(cfg)
        self.reset()

    def reset(self) -> None:
        self.e20, self.e50, self.e200 = Ema(20, keep=6), Ema(50, keep=6), Ema(200, keep=6)
        self.atr = Atr(14)
        self.rsi = Rsi(14)
        self.vol = RollingMean(20)
        self.atr_pct = RollingPercentile(200)
        self.swings = StructureTracker(2)
        self.levels = LevelBook()
        self.highs: deque[float] = deque(maxlen=60)
        self.lows: deque[float] = deque(maxlen=60)
        self.closes: deque[float] = deque(maxlen=10)
        self.opens: deque[float] = deque(maxlen=10)
        self.e20_hist: deque[float] = deque(maxlen=6)
        self.e50_hist: deque[float] = deque(maxlen=6)
        self.breakouts: deque[_Breakout] = deque(maxlen=8)
        self.htf_key: int | None = None
        self.htf_close = 0.0
        self.htf20, self.htf50 = Ema(20), Ema(50)
        self.htf_count = 0
        self.last_index: int | None = None
        self.count = 0
        self.i = -1
        self.rel_vol = 1.0
        self.pct = 50.0
        self.recent_setups: deque[tuple[int, Setup]] = deque(maxlen=12)

    # --- incremental state ---
    def _feed(self, bar: Bar) -> None:
        if self.last_index is not None and bar.index != self.last_index + 1:
            self.reset()
        self.last_index = bar.index
        self.i += 1
        self.count += 1
        prev = self.closes[-1] if self.closes else bar.close
        atr = self.atr.update(bar.high, bar.low, bar.close)
        self.e20_hist.append(self.e20.update(bar.close))
        self.e50_hist.append(self.e50.update(bar.close))
        self.e200.update(bar.close)
        self.rsi.update(bar.close)
        mean_v = self.vol.mean if self.vol.window else 0.0
        self.rel_vol = bar.volume / mean_v if mean_v > 0 else 1.0
        self.vol.update(bar.volume)
        self.pct = self.atr_pct.update(atr)
        for sw in self.swings.update(self.i, bar.time * 1000, bar.high, bar.low, bar.close, atr):
            self.levels.seed(sw.price, self.i, self.rel_vol, atr)
        self.levels.update(self.i, bar.high, bar.low, bar.close, prev, atr)
        # 4x higher-timeframe aggregate (aligned on the higher candle's open time)
        key = bar.time // (4 * self.step)
        if self.htf_key is not None and key != self.htf_key:
            self.htf20.update(self.htf_close)
            self.htf50.update(self.htf_close)
            self.htf_count += 1
        self.htf_key = key
        self.htf_close = bar.close

    def _push_window(self, bar: Bar) -> None:
        self.highs.append(bar.high)
        self.lows.append(bar.low)
        self.closes.append(bar.close)
        self.opens.append(bar.open)

    # --- evaluation ---
    def update(
        self, bar: Bar, snap: AnalysisSnapshot, *, live_block: str | None = None
    ) -> Evaluation:
        """Feed one closed bar (with the canonical snapshot of that bar) and evaluate it."""
        prior_highs, prior_lows = list(self.highs), list(self.lows)
        self._feed(bar)
        try:
            return self._evaluate(bar, snap, prior_highs, prior_lows, live_block)
        finally:
            self._push_window(bar)

    def _wait(
        self,
        bar: Bar,
        buy: float,
        sell: float,
        regime: str,
        trend: str,
        blockers: tuple[str, ...] = (),
        cautions: tuple[str, ...] = (),
        components: dict[str, float] | None = None,
    ) -> Evaluation:
        return Evaluation(
            self.symbol,
            self.timeframe,
            bar.time,
            bar.close_time,
            bar.close,
            round(buy, 1),
            round(sell, 1),
            0,
            round(max(buy, sell), 1),
            "WAIT",
            None,
            None,
            regime,
            trend,
            blockers,
            (),
            cautions,
            components or {},
        )

    def _evaluate(
        self,
        bar: Bar,
        snap: AnalysisSnapshot,
        prior_highs: list[float],
        prior_lows: list[float],
        live_block: str | None,
    ) -> Evaluation:
        atr = self.atr.value or 0.0
        regime = self._regime(snap, atr, prior_highs, prior_lows, bar)
        trend_dir = self._trend_label()
        if self.count < WARMUP or not snap.analysis_ready or atr <= 0:
            return self._wait(bar, 50.0, 50.0, regime.value, trend_dir, ("بيانات غير كافية بعد",))
        if live_block:
            return self._wait(bar, 50.0, 50.0, regime.value, trend_dir, (live_block,))
        if bar.high - bar.low > self.cfg.catastrophic_range_atr * atr:
            return self._wait(bar, 50.0, 50.0, regime.value, trend_dir, ("تذبذب حاد غير طبيعي",))

        setups = self._setups(bar, snap, atr, regime, prior_highs, prior_lows)
        for s in setups:
            self.recent_setups.append((bar.index, s))
        active = [s for idx, s in self.recent_setups if bar.index - idx <= self.cfg.setup_lookback]
        scores: dict[int, tuple[float, dict[str, float], list[str], list[str]]] = {}
        for side in (1, -1):
            own = [s for s in active if s.side == side]
            best = max(own, key=lambda s: s.strength, default=None)
            scores[side] = self._score(side, bar, snap, atr, regime, best)
        buy, sell = scores[1][0], scores[-1][0]
        side = 1 if buy >= sell else -1
        score, comps, reasons, cautions = scores[side]
        other = sell if side == 1 else buy
        own_setups = [s for s in active if s.side == side]
        setup = max(own_setups, key=lambda s: s.strength, default=None)
        if setup is None:
            return self._wait(
                bar,
                buy,
                sell,
                regime.value,
                trend_dir,
                cautions=("لا يوجد إعداد دخول واضح حالياً",),
                components=comps,
            )
        if score - other < self.cfg.margin:
            return self._wait(
                bar,
                buy,
                sell,
                regime.value,
                trend_dir,
                cautions=("لا تفوّق واضح بين الشراء والبيع",),
                components=comps,
            )
        tier = self.cfg.tier(score)
        if tier == "WAIT":
            return self._wait(
                bar, buy, sell, regime.value, trend_dir, cautions=tuple(cautions), components=comps
            )
        plan, problem = self._plan(side, bar, snap, atr, setup)
        if plan is None:
            return self._wait(bar, buy, sell, regime.value, trend_dir, (problem,), components=comps)
        trigger = f"{self.symbol}:{self.timeframe}:{setup.family.value}:{side}:{bar.time}"
        reasons = [f"إعداد: {FAMILY_AR[setup.family.value]} — {setup.note}", *reasons]
        return Evaluation(
            self.symbol,
            self.timeframe,
            bar.time,
            bar.close_time,
            bar.close,
            round(buy, 1),
            round(sell, 1),
            side,
            round(score, 1),
            tier,
            setup,
            plan,
            regime.value,
            trend_dir,
            (),
            tuple(reasons),
            tuple(cautions),
            comps,
            trigger,
        )

    # --- regime / trend ---
    def _trend_side(self) -> float:
        """-1..1 composite trend from EMA order, EMA slope and the 4x aggregate."""
        f, m, s = self.e20.value, self.e50.value, self.e200.value
        if f is None or m is None or s is None:
            return 0.0
        order = 1.0 if f > m > s else -1.0 if f < m < s else (0.4 if f > m else -0.4)
        slope = 0.0
        if len(self.e50_hist) > 1 and self.atr.value:
            slope = _clip((self.e50_hist[-1] - self.e50_hist[0]) / (0.5 * self.atr.value))
        htf = 0.0
        if self.htf_count > 50 and self.htf20.value and self.htf50.value:
            htf = 1.0 if self.htf20.value > self.htf50.value else -1.0
        return _clip(0.5 * order + 0.3 * slope + 0.2 * htf)

    def _trend_label(self) -> str:
        t = self._trend_side()
        return "BULLISH" if t > 0.35 else "BEARISH" if t < -0.35 else "MIXED"

    def _regime(
        self, snap: AnalysisSnapshot, atr: float, highs: list[float], lows: list[float], bar: Bar
    ) -> Regime:
        if not atr or len(highs) < 20:
            return Regime.TRANSITION
        hi, lo = max(highs[-20:]), min(lows[-20:])
        if (bar.close > hi or bar.close < lo) and (bar.high - bar.low) >= 1.2 * atr:
            return Regime.BREAKOUT
        primary = snap.regime.primary.value if snap.regime else "transitional"
        if primary in ("uptrend", "strong_uptrend"):
            return Regime.UPTREND
        if primary in ("downtrend", "strong_downtrend"):
            return Regime.DOWNTREND
        if primary == "low_volatility" or (self.pct < 15 and (hi - lo) < 4 * atr):
            return Regime.COMPRESSION
        if primary == "ranging":
            return Regime.RANGE
        t = self._trend_side()
        if t > 0.6:
            return Regime.UPTREND
        if t < -0.6:
            return Regime.DOWNTREND
        return Regime.TRANSITION

    # --- setups ---
    def _setups(
        self,
        bar: Bar,
        snap: AnalysisSnapshot,
        atr: float,
        regime: Regime,
        highs: list[float],
        lows: list[float],
    ) -> list[Setup]:
        out: list[Setup] = []
        c, o, h, lo = bar.close, bar.open, bar.high, bar.low
        rng = h - lo
        e20, e50 = self.e20.value or c, self.e50.value or c
        trend = self._trend_side()
        idx = bar.index
        events: list[StructureEvent] = []
        for st in (snap.swing_structure, snap.internal_structure):
            if st is not None:
                events.extend(e for e in st.events if idx - e.index <= 2)
        fit = _regime_fit(regime)
        for d in (1, -1):
            body = d * (c - o)
            close_loc = ((c - lo) / rng if d == 1 else (h - c) / rng) if rng > 0 else 0.5
            dir_name = "bullish" if d == 1 else "bearish"
            # 1. trend continuation: aligned trend + structure break in the trend direction
            bos = [e for e in events if e.direction.value == dir_name and e.type.value == "BOS"]
            if d * trend > 0.35 and bos:
                out.append(
                    Setup(
                        Family.TREND_CONTINUATION,
                        d,
                        0.6 + 0.4 * min(1.0, d * trend),
                        _extreme(lows, highs, d, 3),
                        "كسر هيكل مع الاتجاه",
                    )
                )
            # 2. pullback to EMA20/50 in a trend, closing back in the trend direction
            touch = lo if d == 1 else h
            zone_hi, zone_lo = max(e20, e50) + 0.3 * atr, min(e20, e50) - 0.3 * atr
            if d * trend > 0.2 and zone_lo <= touch <= zone_hi and d * (c - e20) > 0 and body > 0:
                out.append(
                    Setup(
                        Family.PULLBACK,
                        d,
                        0.55 + 0.35 * close_loc,
                        touch,
                        "ارتداد من منطقة EMA20/50",
                    )
                )
            # 3. breakout of the prior 20-candle range with a real body
            if len(highs) >= 20:
                edge = max(highs[-20:]) if d == 1 else min(lows[-20:])
                if d * (c - edge) > 0.1 * atr and body >= 0.5 * atr:
                    vol = min(1.0, max(0.0, self.rel_vol - 0.8))
                    out.append(
                        Setup(
                            Family.BREAKOUT,
                            d,
                            0.55 + 0.25 * vol + 0.2 * close_loc,
                            edge,
                            "إغلاق خارج نطاق آخر 20 شمعة",
                        )
                    )
                    self.breakouts.append(_Breakout(idx, edge, d))
            # 4. breakout + retest of the broken level
            for b in self.breakouts:
                if b.side != d or not 2 <= idx - b.index <= 15:
                    continue
                if abs(touch - b.level) <= 0.3 * atr and d * (c - b.level) > 0.1 * atr and body > 0:
                    out.append(
                        Setup(
                            Family.BREAKOUT_RETEST, d, 0.75, b.level, "إعادة اختبار مستوى الاختراق"
                        )
                    )
                    break
            # 5. momentum continuation
            if len(self.closes) >= 3:
                roc = d * (c - self.closes[-3]) / atr
                ext = d * (c - e20) / atr
                rsi = self.rsi.value if d == 1 else 100 - self.rsi.value
                if roc >= 1.5 and close_loc >= 0.6 and rsi > 55 and ext < 4:
                    out.append(
                        Setup(
                            Family.MOMENTUM,
                            d,
                            min(1.0, 0.5 + 0.15 * roc),
                            _extreme(lows, highs, d, 3),
                            "زخم قوي مستمر",
                        )
                    )
            # 6/7. support / resistance reaction (levels with strength)
            near = self.levels.nearest(c, above=d == -1, i=self.i, min_grade="medium")[:1]
            for lv in near:
                p = lv.price
                tested = (lo <= p + 0.25 * atr) if d == 1 else (h >= p - 0.25 * atr)
                away = d * (c - p) >= 0.3 * atr
                wick = (min(o, c) - lo) if d == 1 else (h - max(o, c))
                if tested and away and rng > 0 and wick / rng >= 0.35:
                    fam = Family.SUPPORT_REACTION if d == 1 else Family.RESISTANCE_REACTION
                    grade = lv.grade(self.i)
                    out.append(
                        Setup(
                            fam,
                            d,
                            0.85 if grade == "strong" else 0.65,
                            p,
                            ("ارتداد من دعم " if d == 1 else "رفض من مقاومة ")
                            + ("قوي" if grade == "strong" else "متوسط"),
                        )
                    )
            # 8. liquidity sweep reversal (canonical sweeps)
            good = "sell_side" if d == 1 else "buy_side"
            if snap.liquidity is not None:
                for s in snap.liquidity.sweeps:
                    if s.side.value == good and idx - s.index <= 1 and d * (c - s.level) > 0:
                        out.append(
                            Setup(
                                Family.LIQUIDITY_SWEEP,
                                d,
                                0.6 + 0.4 * min(1.0, s.quality),
                                s.extreme,
                                "سحب سيولة ثم عودة",
                            )
                        )
                        break
            # 9. range edge reversal
            if regime in (Regime.RANGE, Regime.COMPRESSION) and len(highs) >= 30:
                hi, lw = max(highs[-30:]), min(lows[-30:])
                if hi > lw:
                    pos = (c - lw) / (hi - lw)
                    edge_ok = pos <= 0.25 if d == 1 else pos >= 0.75
                    if edge_ok and body > 0 and close_loc >= 0.55:
                        out.append(
                            Setup(
                                Family.RANGE_EDGE,
                                d,
                                0.65,
                                lw if d == 1 else hi,
                                "ارتداد من حافة النطاق",
                            )
                        )
            # 10. structure reversal (CHoCH)
            choch = [e for e in events if e.direction.value == dir_name and e.type.value == "CHOCH"]
            if choch and body > 0:
                out.append(
                    Setup(
                        Family.STRUCTURE_REVERSAL,
                        d,
                        0.65,
                        _extreme(lows, highs, d, 5),
                        "تغيّر هيكل السوق (CHoCH)",
                    )
                )
        return [
            Setup(s.family, s.side, round(s.strength * fit[s.family], 3), s.anchor, s.note)
            for s in out
        ]

    # --- scoring ---
    def _score(
        self,
        d: int,
        bar: Bar,
        snap: AnalysisSnapshot,
        atr: float,
        regime: Regime,
        setup: Setup | None,
    ) -> tuple[float, dict[str, float], list[str], list[str]]:
        k: dict[str, float] = {}
        pro: list[str] = []
        con: list[str] = []
        c = bar.close
        # trend
        t = d * self._trend_side()
        k["trend"] = t
        (pro if t > 0.35 else con if t < -0.35 else []).append(
            "الاتجاه (EMA 20/50/200) " + ("متوافق" if t > 0.35 else "معاكس")
        ) if abs(t) > 0.35 else None
        # structure
        st = 0.0
        if snap.swing_structure is not None:
            sd = snap.swing_structure.direction.value
            st += (
                0.6
                if sd == ("bullish" if d == 1 else "bearish")
                else -0.6
                if sd != "neutral"
                else 0
            )
        if snap.internal_structure is not None:
            idir = snap.internal_structure.direction.value
            st += (
                0.4
                if idir == ("bullish" if d == 1 else "bearish")
                else -0.4
                if idir != "neutral"
                else 0
            )
        k["structure"] = _clip(st)
        if st >= 0.6:
            pro.append("هيكل السوق متوافق (HH/HL)" if d == 1 else "هيكل السوق متوافق (LH/LL)")
        elif st <= -0.6:
            con.append("هيكل السوق معاكس")
        # multi-timeframe
        m, n = 0.0, 0
        if snap.multi_timeframe is not None:
            for fr in snap.multi_timeframe.higher:
                if fr.trend is not None:
                    m += (
                        1
                        if fr.trend.value == ("bullish" if d == 1 else "bearish")
                        else -1
                        if fr.trend.value != "neutral"
                        else 0
                    )
                    n += 1
        if self.htf_count > 50 and self.htf20.value and self.htf50.value:
            m += d * (1 if self.htf20.value > self.htf50.value else -1)
            n += 1
        k["mtf"] = m / n if n else 0.0
        if k["mtf"] >= 0.5:
            pro.append("الإطار الأعلى متوافق")
        elif k["mtf"] <= -0.5:
            con.append("الإطار الأعلى معاكس (يُخفّض الجودة)")
        # momentum (a strong breakout may run with a high RSI)
        rsi = self.rsi.value if d == 1 else 100 - self.rsi.value
        slope = d * self.rsi.slope()
        mo = _clip((rsi - 50) / 25) * 0.7 + _clip(slope / 10) * 0.3
        breakout = setup is not None and setup.family in (Family.BREAKOUT, Family.MOMENTUM)
        if rsi > 80 and not breakout:
            mo -= 0.5
            con.append("زخم متشبع")
        k["momentum"] = _clip(mo)
        if mo > 0.4:
            pro.append("الزخم داعم")
        # volume
        body = d * (c - bar.open)
        if self.rel_vol >= 1.2 and body > 0:
            k["volume"] = min(1.0, self.rel_vol - 1.0)
            pro.append("حجم تداول أعلى من المتوسط")
        elif self.rel_vol < 0.6:
            k["volume"] = -0.3
            con.append("حجم تداول ضعيف")
        else:
            k["volume"] = 0.0
        # location: room to the opposing level, premium/discount, extension
        loc = 0.0
        opp = self.levels.nearest(c, above=d == 1, i=self.i, min_grade="medium")[:1]
        if opp:
            room = d * (opp[0].price - c) / atr
            loc += 0.5 if room >= 2 else 0.1 if room >= 1 else -0.5
            if room < 1:
                con.append("مستوى معاكس قريب — مساحة محدودة")
        else:
            loc += 0.4
        pd = snap.premium_discount
        if pd is not None:
            pos = pd.position / 100
            loc += 0.3 * ((0.5 - pos) * 2 * d)
        ext = d * (c - (self.e20.value or c)) / atr
        if ext > 3:
            loc -= 0.5
            con.append("السعر ممتد بعيداً عن EMA20")
        k["location"] = _clip(loc)
        # setup strength
        k["setup"] = setup.strength if setup is not None else 0.0
        # candle
        rng = bar.high - bar.low
        if rng > 0:
            cl = (c - bar.low) / rng if d == 1 else (bar.high - c) / rng
            k["candle"] = _clip((cl - 0.5) * 2)
        else:
            k["candle"] = 0.0
        # regime fit for the side
        rg = {Regime.UPTREND: d, Regime.DOWNTREND: -d}.get(regime, 0.0)
        if regime is Regime.TRANSITION:
            rg = -0.2
        k["regime"] = float(rg)
        total = sum(self.cfg.weight(name) for name in k)
        raw = sum(self.cfg.weight(name) * v for name, v in k.items())
        score = 50.0 + 50.0 * raw / total
        return max(0.0, min(100.0, score)), {n: round(v, 3) for n, v in k.items()}, pro, con

    # --- plan ---
    def _plan(
        self, d: int, bar: Bar, snap: AnalysisSnapshot, atr: float, setup: Setup
    ) -> tuple[Plan | None, str]:
        cfg = self.cfg
        entry = bar.close
        tick = max(atr * 1e-4, 1e-12)
        anchor = (
            setup.anchor
            if setup.anchor is not None
            else _extreme(list(self.lows), list(self.highs), d, 3)
        )
        recent = (
            min([*list(self.lows)[-2:], bar.low])
            if d == 1
            else max([*list(self.highs)[-2:], bar.high])
        )
        structural = min(anchor, recent) if d == 1 else max(anchor, recent)
        stop = structural - d * cfg.stop_buffer_atr * atr
        dist = d * (entry - stop)
        source = "structure"
        if dist < cfg.min_stop_atr * atr:
            stop = entry - d * cfg.min_stop_atr * atr  # never inside the noise
            source = "structure+atr_floor"
        elif dist > cfg.max_stop_atr * atr:
            return None, "وقف الخسارة الهيكلي بعيد جداً — هندسة صفقة غير صالحة"
        risk = d * (entry - stop)
        if risk <= tick:
            return None, "وقف خسارة غير ممكن"
        # structural targets: opposing S/R levels, active liquidity pools, recent swing extremes
        cands: list[tuple[float, str]] = []
        for lv in self.levels.nearest(entry, above=d == 1, i=self.i, min_grade="weak")[:6]:
            cands.append((lv.price, "level"))
        if snap.liquidity is not None:
            want = "buy_side" if d == 1 else "sell_side"
            for p in snap.liquidity.pools:
                if (
                    p.status.value == "active"
                    and p.side.value == want
                    and d * (p.level - entry) > 0
                ):
                    cands.append((p.level, "liquidity"))
        ext = max(self.highs) if d == 1 else min(self.lows)
        if d * (ext - entry) > 0:
            cands.append((ext, "swing"))
        cands.sort(key=lambda x: d * (x[0] - entry))
        targets: list[tuple[float, str]] = []
        need = (cfg.min_rr_tp1, cfg.min_rr_tp2, cfg.min_rr_tp2 + 1.0)
        floor_r = (1.2, 2.0, 3.0)
        last_r = 0.0
        for n in range(3):
            pick = None
            for price, src in cands:
                r = d * (price - entry) / risk
                if r >= max(need[n], last_r + 0.4) and r <= 6.0:
                    pick = (price, src)
                    break
            if pick is None:
                r = max(floor_r[n], last_r + 0.6)
                pick = (entry + d * r * risk, f"{r:.1f}R")
            last_r = d * (pick[0] - entry) / risk
            targets.append(pick)
        plan = Plan(
            side=d,
            entry=entry,
            stop=stop,
            targets=(targets[0][0], targets[1][0], targets[2][0]),
            target_sources=(targets[0][1], targets[1][1], targets[2][1]),
            stop_source=source,
        )
        return plan, ""


def _extreme(lows: list[float], highs: list[float], d: int, n: int) -> float:
    if d == 1:
        return min(lows[-n:]) if lows else 0.0
    return max(highs[-n:]) if highs else 0.0


def _regime_fit(regime: Regime) -> dict[Family, float]:
    """How appropriate each family is for the regime (multiplies the setup strength)."""
    base = dict.fromkeys(Family, 0.85)
    if regime in (Regime.UPTREND, Regime.DOWNTREND):
        for f in (
            Family.TREND_CONTINUATION,
            Family.PULLBACK,
            Family.BREAKOUT_RETEST,
            Family.MOMENTUM,
        ):
            base[f] = 1.0
        base[Family.RANGE_EDGE] = 0.6
    elif regime is Regime.RANGE:
        for f in (
            Family.SUPPORT_REACTION,
            Family.RESISTANCE_REACTION,
            Family.RANGE_EDGE,
            Family.LIQUIDITY_SWEEP,
        ):
            base[f] = 1.0
        base[Family.MOMENTUM] = 0.7
        base[Family.TREND_CONTINUATION] = 0.7
    elif regime in (Regime.COMPRESSION, Regime.BREAKOUT):
        for f in (Family.BREAKOUT, Family.BREAKOUT_RETEST, Family.MOMENTUM):
            base[f] = 1.0
    return base
