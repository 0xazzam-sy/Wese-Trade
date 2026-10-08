"""Execution engine: entry timing on 1m / 5m / 10m for an active Strategy 4.2 parent setup.

Pure functions over closed-candle features. Hierarchy:

    parent (Strategy 4.2: direction, setup, invalidation, targets)
      -> location (is the entry zone still valid? extended? missed?)
      -> execution evidence (EMA, structure BOS/CHoCH, S/R reaction, liquidity sweep,
         momentum, candle, regime, live microstructure) -> «قوة توقيت الدخول» 0-100
      -> trigger on THIS closed candle -> BUY / SELL confirmation, else WAIT

The score is a weighted description of how favourable current execution conditions are for
the parent trade. It is NOT a probability of winning. Nothing here can create a trade
without an open parent, and nothing can trade against the parent's direction.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.execution.models import (
    Decision,
    Evaluation,
    ExecState,
    ExecutionSignal,
    Features,
    Micro,
    ParentSetup,
    Plan,
)

PARENT_TIMEFRAMES: dict[str, tuple[str, ...]] = {
    "1m": ("15m", "30m"),
    "5m": ("15m", "30m"),
    "10m": ("30m", "1h"),
}
STEP_SECONDS = {"1m": 60, "5m": 300, "10m": 600}
MAX_BARS = {"1m": 240, "5m": 144, "10m": 96}  # holding limit after confirmation
CONFIRM_SCORE = 60.0
RECENT_BARS = 6  # structure events / sweeps this recent still count as evidence
IDEAL_PAD_ATR = 0.25  # the parent entry zone, padded by this many execution ATRs
ACCEPT_PROGRESS_R = 0.35  # beyond the parent entry toward the targets (R units)
MISSED_PROGRESS_R = 0.6
MIN_RR_TP1 = 1.0
MISSED_RR_TP1 = 0.8
SPREAD_ABNORMAL = 3.0  # x the normal spread

WEIGHTS = {
    "ema": 12.0,
    "structure": 18.0,
    "level": 12.0,
    "liquidity": 12.0,
    "momentum": 12.0,
    "candle": 8.0,
    "regime": 10.0,
    "location": 10.0,
    "micro": 6.0,
}
TRIGGER_AR = {
    "ema_reclaim": "استعادة EMA20",
    "choch": "تغيّر هيكل داخلي (CHoCH)",
    "bos": "كسر هيكل داخلي (BOS)",
    "sweep_reclaim": "سحب سيولة ثم استعادة",
    "level_reaction": "ارتداد من مستوى",
    "momentum_recovery": "تعافي الزخم",
}
GRADE_VALUE = {"strong": 1.0, "medium": 0.8, "weak": 0.5}


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return lo if x < lo else hi if x > hi else x


def score_band(score: float) -> str:
    if score >= 85:
        return "very_strong"
    if score >= 75:
        return "strong"
    if score >= 60:
        return "acceptable"
    if score >= 40:
        return "weak"
    return "poor"


# --- parent selection -------------------------------------------------------------------------
def select_parent(
    timeframe: str, candidates: Iterable[ParentSetup]
) -> tuple[ParentSetup | None, bool]:
    """(parent, conflict). The most recent open parent of the mapped higher timeframes;
    open parents with opposite directions are a conflict (no execution)."""
    allowed = PARENT_TIMEFRAMES.get(timeframe, ())
    live = [p for p in candidates if p.timeframe in allowed and p.is_open]
    if not live:
        return None, False
    if len({p.side for p in live}) > 1:
        return None, True
    return max(live, key=lambda p: (p.confirmed_time, -allowed.index(p.timeframe))), False


# --- plan -------------------------------------------------------------------------------------
def build_plan(parent: ParentSetup, entry: float, f: Features) -> Plan:
    """Entry = the execution price; stop starts from the parent invalidation and is tightened
    to execution structure only when that stop is structurally valid and outside the noise."""
    d = parent.side
    stop, source = parent.stop, "parent"
    buffer = max(0.25 * f.atr, 3 * f.tick)
    swing = f.swing_low if d == 1 else f.swing_high
    if swing is not None and f.atr > 0:
        candidate = swing - d * buffer
        tighter = d * (candidate - parent.stop) > 0
        room = d * (entry - candidate)
        if tighter and room >= max(1.5 * f.atr, 0.5 * d * (entry - parent.stop)):
            stop, source = candidate, "execution_structure"
    return Plan(
        side=d,
        entry=entry,
        parent_entry=parent.entry,
        stop=stop,
        parent_stop=parent.stop,
        stop_source=source,
        targets=parent.targets,
        target_sources=("parent_tp1", "parent_tp2", "parent_tp3"),
    )


# --- evaluation -------------------------------------------------------------------------------
def _location(parent: ParentSetup, f: Features) -> tuple[str, float, float]:
    """(zone, progress_r, rr_tp1_now): ideal | acceptable | extended | missed | invalid."""
    d = parent.side
    r = parent.risk
    price = f.close
    if r <= 0:
        return "invalid", 0.0, 0.0
    progress = d * (price - parent.entry) / r
    room = d * (price - parent.stop)
    if room <= 0 or d * (price - parent.invalidation) <= 0:
        return "invalid", progress, 0.0
    rr1 = d * (parent.targets[0] - price) / room
    if (
        parent.state in ("tp1_hit", "tp2_hit")
        or progress > MISSED_PROGRESS_R
        or rr1 < MISSED_RR_TP1
    ):
        return "missed", progress, rr1
    pad = IDEAL_PAD_ATR * f.atr
    lo, hi = parent.entry_low - pad, parent.entry_high + pad
    if lo <= price <= hi or progress <= 0:
        return "ideal", progress, rr1
    if progress <= ACCEPT_PROGRESS_R:
        return "acceptable", progress, rr1
    return "extended", progress, rr1


def _components(
    d: int, f: Features, zone: str, micro: Micro | None
) -> tuple[dict[str, float], list[str], list[str], list[str]]:
    """Signed evidence per component (-1..1, + = favours the parent direction), reasons,
    cautions and the triggers that fired on this candle."""
    reasons: list[str] = []
    cautions: list[str] = []
    triggers: list[str] = []
    k: dict[str, float] = {}
    c, atr = f.close, f.atr
    bullish_side = "bullish" if d == 1 else "bearish"

    # EMA
    ema = 0.0
    if f.ema20 is not None:
        above = d * (c - f.ema20) > 0
        rising = f.ema20_prev is not None and d * (f.ema20 - f.ema20_prev) > 0
        ordered = f.ema50 is not None and d * (f.ema20 - f.ema50) > 0
        if above and rising and ordered:
            ema = 1.0
            reasons.append(
                "EMA20 فوق EMA50 والسعر أعلاها" if d == 1 else "EMA20 تحت EMA50 والسعر أسفلها"
            )
        elif above:
            ema = 0.5
        elif not rising and not ordered:
            ema = -1.0
            cautions.append("ترتيب EMA ما زال عكس اتجاه الصفقة")
        else:
            ema = -0.5
            cautions.append("السعر لم يستعد EMA20 بعد")
        if (
            f.ema20_prev is not None
            and d * (f.prev_close - f.ema20_prev) <= 0
            and d * (c - f.ema20) > 0
        ):
            triggers.append("ema_reclaim")
    k["ema"] = ema

    # Structure (internal BOS / CHoCH)
    structure = 0.0
    recent = [e for e in f.structure_events if f.index - e[0] < RECENT_BARS]
    if recent:
        t, kind, direction = recent[-1]
        sign = 1 if direction == bullish_side else -1
        structure = sign * (1.0 if kind == "CHOCH" else 0.8)
        if sign > 0:
            reasons.append(
                ("تم تأكيد CHoCH داخلي" if kind == "CHOCH" else "تم تأكيد BOS داخلي")
                + (" صاعد" if d == 1 else " هابط")
            )
            if t == f.index:
                triggers.append("choch" if kind == "CHOCH" else "bos")
        else:
            cautions.append("آخر كسر هيكل داخلي عكس اتجاه الصفقة")
    elif f.direction == bullish_side:
        structure = 0.3
    elif f.direction not in ("neutral", bullish_side):
        structure = -0.3
        cautions.append("الهيكل الداخلي لم يتحول بعد لصالح الصفقة")
    k["structure"] = structure

    # Support / resistance reaction and location against opposing levels
    level = 0.0
    own = f.supports if d == 1 else f.resistances
    opposing = f.resistances if d == 1 else f.supports
    if own and atr > 0:
        lv = own[0]
        touch = f.low if d == 1 else f.high
        reacted = d * (touch - lv.price) <= 0.3 * atr and d * (c - lv.price) > 0
        if reacted and d * (lv.price - c) > -1.0 * atr:
            level = GRADE_VALUE.get(lv.grade, 0.5)
            name = "دعم" if d == 1 else "مقاومة"
            strength = {"strong": "قوي", "medium": "متوسط", "weak": "ضعيف"}[lv.grade]
            reasons.append(f"السعر أعاد اختبار {name} {strength} وارتد منه")
            triggers.append("level_reaction")
    if opposing and atr > 0 and d * (opposing[0].price - c) < 0.5 * atr:
        level = min(level, 0.0) - (0.6 if opposing[0].grade != "weak" else 0.3)
        cautions.append("مستوى معاكس قريب جداً من السعر")
    k["level"] = _clip(level)

    # Liquidity sweep (sell-side sweep favours longs, buy-side sweep favours shorts)
    liquidity = 0.0
    good, bad = ("sell_side", "buy_side") if d == 1 else ("buy_side", "sell_side")
    for t, side, _lvl in reversed(f.sweeps):
        if f.index - t >= 5:
            break
        if side == good:
            liquidity = 1.0
            reasons.append("تم سحب السيولة " + ("السفلية" if d == 1 else "العلوية"))
            if t == f.index and d * (c - f.open) > 0:
                triggers.append("sweep_reclaim")
            break
        if side == bad:
            liquidity = -0.7
            cautions.append("سُحبت سيولة في اتجاه معاكس مؤخراً")
            break
    k["liquidity"] = liquidity

    # Momentum (RSI level and slope)
    momentum = 0.0
    if f.rsi is not None:
        rsi_d = f.rsi if d == 1 else 100 - f.rsi
        slope = (f.rsi_slope or 0.0) * d
        if slope > 0 and 45 <= rsi_d <= 72:
            momentum = 1.0
            reasons.append("الزخم تحسن")
            if rsi_d - slope < 50 <= rsi_d:
                triggers.append("momentum_recovery")
        elif rsi_d > 78:
            momentum = -0.5
            cautions.append("الزخم متشبع — احتمال تصحيح قبل الدخول")
        elif slope < 0 and rsi_d < 45:
            momentum = -1.0
            cautions.append("الزخم ما زال ضعيفاً")
        else:
            momentum = _clip((rsi_d - 50) / 25) * 0.5
    k["momentum"] = momentum

    # Confirmation candle
    rng = f.high - f.low
    candle = 0.0
    if rng > 0:
        loc = (c - f.low) / rng if d == 1 else (f.high - c) / rng
        body = d * (c - f.open)
        if loc >= 0.6 and body > 0:
            candle = 1.0
        elif loc <= 0.3 and body < 0:
            candle = -1.0
        else:
            candle = _clip(2 * loc - 1) * 0.5
    k["candle"] = candle

    # Execution-timeframe regime
    regime = 0.0
    with_trend = ("uptrend", "strong_uptrend") if d == 1 else ("downtrend", "strong_downtrend")
    against = ("downtrend", "strong_downtrend") if d == 1 else ("uptrend", "strong_uptrend")
    if f.regime in with_trend:
        regime = 1.0
        reasons.append("اتجاه الفريم الحالي متوافق مع الصفقة")
    elif f.regime in against:
        regime = -1.0
        cautions.append("اتجاه الفريم الحالي ما زال معاكساً")
    elif f.regime == "high_volatility":
        regime = -0.3
        cautions.append("تذبذب مرتفع")
    k["regime"] = regime

    # Location relative to the parent entry zone
    k["location"] = {"ideal": 1.0, "acceptable": 0.3, "extended": -1.0}.get(zone, -1.0)
    if zone == "ideal":
        reasons.append("السعر داخل منطقة الدخول")
    elif zone == "extended":
        cautions.append("السعر ممتد بعيداً عن منطقة الدخول")

    # Live microstructure (optional)
    m = 0.0
    if micro is not None and micro.available:
        flow = micro.flow_imbalance or 0.0
        book = micro.book_imbalance or 0.0
        m = _clip(d * (0.6 * flow + 0.4 * book) * 2)
        if m > 0.3:
            reasons.append("ضغط التداول اللحظي يدعم الصفقة")
        elif m < -0.3:
            cautions.append("ضغط التداول اللحظي معاكس مؤقتاً")
        if micro.status == "degraded":
            m = min(m, 0.0) - 0.5
    k["micro"] = _clip(m)
    return k, reasons, cautions, triggers


def _score(k: dict[str, float], micro: Micro | None) -> float:
    total = sum(WEIGHTS.values())
    raw = sum(WEIGHTS[n] * v for n, v in k.items())
    score = 50.0 + 50.0 * raw / total
    if micro is not None:
        if micro.status == "stale":
            score -= 15
        if (
            micro.spread_bp is not None
            and micro.spread_normal_bp
            and micro.spread_bp > SPREAD_ABNORMAL * micro.spread_normal_bp
        ):
            score -= 10
    return round(max(0.0, min(100.0, score)), 1)


def _headline(decision: Decision, d: int, zone: str, parent: ParentSetup | None) -> str:
    if decision is Decision.NO_SETUP:
        return "لا توجد فرصة تداول مؤكدة حالياً."
    if decision is Decision.ENTRY_MISSED:
        return "فاتت منطقة الدخول — لا تلاحق السعر."
    if decision in (Decision.BUY, Decision.SELL):
        return (
            "تم تأكيد توقيت الدخول للصفقة الصاعدة."
            if d == 1
            else "تم تأكيد توقيت الدخول للصفقة الهابطة."
        )
    if zone == "extended":
        return (
            "الاتجاه الشرائي مؤكد، بانتظار إعادة اختبار منطقة الدخول."
            if d == 1
            else "الاتجاه البيعي مؤكد، بانتظار إعادة اختبار منطقة الدخول."
        )
    return (
        "الصفقة صاعدة لكن توقيت الدخول غير مناسب بعد."
        if d == 1
        else "الصفقة هابطة لكن توقيت الدخول غير مناسب بعد."
    )


def evaluate(
    symbol: str,
    timeframe: str,
    f: Features | None,
    parent: ParentSetup | None,
    *,
    conflict: bool = False,
    micro: Micro | None = None,
    signal: ExecutionSignal | None = None,
) -> Evaluation:
    """Execution decision for the last CLOSED candle. `signal` = this stream's execution
    signal for the same parent (if one was already confirmed)."""
    candle_time = f.time if f is not None else None
    if parent is None or not parent.is_open:
        why = (
            "تعارض بين إشارات الإطارات الأعلى — لا دخول حتى يتضح الاتجاه."
            if conflict
            else "لا توجد فرصة تداول مؤكدة حالياً."
        )
        return Evaluation(
            symbol, timeframe, candle_time, Decision.NO_SETUP, 0.0, 0, None, None, (), (), why,
            micro=micro,
        )  # fmt: skip
    d = parent.side
    if signal is not None and signal.parent.signal_id == parent.signal_id:
        return _from_signal(symbol, timeframe, candle_time, signal, micro)
    if f is None or f.atr <= 0:
        return Evaluation(
            symbol, timeframe, candle_time, Decision.WAIT, 0.0, d, parent,
            build_plan(parent, parent.entry, f) if f is not None else None, (),
            ("بيانات الفريم غير كافية بعد",), _headline(Decision.WAIT, d, "", parent),
            micro=micro,
        )  # fmt: skip
    zone, _progress, _rr1 = _location(parent, f)
    k, reasons, cautions, triggers = _components(d, f, zone, micro)
    score = _score(k, micro)
    parent_reason = (
        f"اتجاه {parent.timeframe} " + ("صاعد" if d == 1 else "هابط") + " (Strategy 4.2)"
    )
    reasons = [parent_reason, *reasons]
    if micro is not None and micro.status == "stale":
        cautions.append("بيانات السوق اللحظية متأخرة — لا تأكيد جديد")
    if zone == "invalid":
        return Evaluation(
            symbol, timeframe, candle_time, Decision.NO_SETUP, score, d, parent, None,
            tuple(reasons), ("السعر تجاوز مستوى إبطال الفرصة",),
            "لا توجد فرصة تداول مؤكدة حالياً.", k, micro,
        )  # fmt: skip
    if zone == "missed":
        return Evaluation(
            symbol, timeframe, candle_time, Decision.ENTRY_MISSED, score, d, parent,
            build_plan(parent, parent.entry, f), tuple(reasons),
            ("تحرك السعر بعيداً عن منطقة الدخول",),
            _headline(Decision.ENTRY_MISSED, d, zone, parent), k, micro,
        )  # fmt: skip
    plan = build_plan(parent, f.close, f)
    blocked = micro is not None and micro.status == "stale"
    confirm = (
        bool(triggers)
        and score >= CONFIRM_SCORE
        and zone in ("ideal", "acceptable")
        and d * (f.close - f.open) > 0
        and plan.rr[0] >= MIN_RR_TP1
        and not blocked
    )
    if confirm:
        decision = Decision.BUY if d == 1 else Decision.SELL
        trigger = triggers[0]
        reasons.insert(1, "التأكيد: " + "، ".join(TRIGGER_AR[t] for t in triggers))
    else:
        decision = Decision.WAIT
        trigger = None
        if not triggers:
            cautions.append("لا توجد شمعة تأكيد على هذا الفريم بعد")
        elif score < CONFIRM_SCORE:
            cautions.append("قوة التوقيت أقل من حد التأكيد")
        elif plan.rr[0] < MIN_RR_TP1:
            cautions.append("العائد إلى الهدف الأول غير كافٍ من السعر الحالي")
        plan = build_plan(parent, parent.entry, f)  # show the zone entry while waiting
    return Evaluation(
        symbol, timeframe, candle_time, decision, score, d, parent, plan, tuple(reasons),
        tuple(dict.fromkeys(cautions)), _headline(decision, d, zone, parent), k, micro, trigger,
    )  # fmt: skip


def _from_signal(
    symbol: str, timeframe: str, candle_time: int | None, s: ExecutionSignal, micro: Micro | None
) -> Evaluation:
    """While an execution signal for this parent exists, the stream shows it (no re-entry)."""
    d = s.side
    if s.state is ExecState.ENTRY_MISSED:
        decision, head = Decision.ENTRY_MISSED, "فاتت منطقة الدخول — لا تلاحق السعر."
    elif s.state.is_final:
        decision, head = Decision.NO_SETUP, "انتهت صفقة التنفيذ لهذه الفرصة."
    else:
        decision = Decision.BUY if d == 1 else Decision.SELL
        head = (
            "تم تأكيد توقيت الدخول للصفقة الصاعدة."
            if d == 1
            else "تم تأكيد توقيت الدخول للصفقة الهابطة."
        )
    return Evaluation(
        symbol, timeframe, candle_time, decision, s.score, d, s.parent, s.plan, s.reasons, (),
        head, micro=micro, trigger=s.trigger,
    )  # fmt: skip


# --- confirmation -> signal, lifecycle --------------------------------------------------------
def valid_until(timeframe: str, close_time: int) -> int:
    step = STEP_SECONDS.get(timeframe, 60)
    return close_time + (step // 2 if timeframe == "10m" else step)


def signal_id(symbol: str, timeframe: str, parent_id: str, close_time: int) -> str:
    return f"x-{symbol}-{timeframe}-{parent_id[-16:]}-{close_time}"


def confirm(ev: Evaluation, f: Features) -> ExecutionSignal | None:
    if ev.decision not in (Decision.BUY, Decision.SELL) or ev.parent is None or ev.plan is None:
        return None
    if ev.trigger is None:  # a carried-over signal view, not a new confirmation
        return None
    s = ExecutionSignal(
        id=signal_id(ev.symbol, ev.timeframe, ev.parent.signal_id, f.close_time),
        symbol=ev.symbol,
        timeframe=ev.timeframe,
        side=ev.side,
        score=ev.score,
        confirmed_time=f.close_time,
        candle_time=f.time,
        valid_until=valid_until(ev.timeframe, f.close_time),
        plan=ev.plan,
        parent=ev.parent,
        reasons=ev.reasons,
        trigger=ev.trigger,
        micro=None
        if ev.micro is None
        else {"status": ev.micro.status, "spread_bp": ev.micro.spread_bp},
        state_time=f.close_time,
        cursor=f.close_time,
    )
    s.history.append((f.close_time, ExecState.READY.value))
    return s


def _set(s: ExecutionSignal, state: ExecState, when: int) -> None:
    s.state = state
    s.state_time = when
    s.history.append((when, state.value))
    if state.is_final:
        s.closed_time = when


def advance(
    s: ExecutionSignal, high: float, low: float, close_time: int, parent_state: str | None = None
) -> bool:
    """Advance one closed candle after confirmation. Returns True if the state changed.
    Same-candle stop and target: the stop counts first (conservative)."""
    if not s.is_open or close_time <= max(s.confirmed_time, s.cursor):
        return False
    s.cursor = close_time
    before = s.state
    d, p = s.side, s.plan
    s.bars += 1
    if s.state is ExecState.READY:
        if d * (p.targets[0] - (high if d == 1 else low)) <= 0:
            _set(s, ExecState.ENTRY_MISSED, close_time)  # ran to TP1 without the entry
            return True
        if (d == 1 and low <= p.entry) or (d == -1 and high >= p.entry):
            s.entered_time = close_time
            _set(s, ExecState.ACTIVE, close_time)
        elif parent_state in ("stopped", "invalidated", "expired", "closed"):
            _set(s, ExecState.EXPIRED, close_time)
            return True
        elif close_time > s.valid_until:
            _set(s, ExecState.ENTRY_MISSED, close_time)
            return True
        else:
            return False
    if (d == 1 and low <= p.stop) or (d == -1 and high >= p.stop):
        _set(s, ExecState.STOPPED, close_time)
        return True
    extreme = high if d == 1 else low
    hit = sum(1 for t in p.targets if d * (extreme - t) >= 0)
    if hit > s.targets_hit:
        s.targets_hit = hit
        _set(s, (ExecState.TP1_HIT, ExecState.TP2_HIT, ExecState.TP3_HIT)[hit - 1], close_time)
    if s.is_open and s.bars > MAX_BARS.get(s.timeframe, 240):
        _set(s, ExecState.EXPIRED, close_time)
    return s.state is not before
