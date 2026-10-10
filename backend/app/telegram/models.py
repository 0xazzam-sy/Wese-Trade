"""Telegram notification domain types and the Arabic message format.

A `SignalAlert` is built from the canonical persisted signal (Strategy 4.3 on 15m / 30m /
1h, or an execution confirmation on 1m / 5m / 10m) — Telegram never computes its own
levels. Events: NEW, TP1, TP2, TP3, STOPPED, EXPIRED.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

EVENTS: tuple[str, ...] = ("NEW", "TP1", "TP2", "TP3", "STOPPED", "EXPIRED")
DEFAULT_EVENTS: dict[str, bool] = {
    "NEW": True,
    "TP1": True,
    "TP2": True,
    "TP3": True,
    "STOPPED": True,
    "EXPIRED": False,
}
LIFECYCLE_EVENTS = frozenset(EVENTS) - {"NEW"}
SIGNAL_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "10m", "15m", "30m", "1h")

TIER_AR = {"A+": "استثنائية", "A": "قوية", "B": "جيدة", "C": "مقبولة"}
EVENT_TITLE = {
    "NEW": "🚨 Wese Trade — إشارة جديدة",
    "TP1": "✅ Wese Trade — تحقق الهدف 1",
    "TP2": "✅ Wese Trade — تحقق الهدف 2",
    "TP3": "🏁 Wese Trade — تحقق الهدف 3",
    "STOPPED": "⛔ Wese Trade — ضُرب وقف الخسارة",
    "EXPIRED": "⌛ Wese Trade — انتهت صلاحية الإشارة",
}


@dataclass(frozen=True, slots=True)
class SignalAlert:
    signal_id: str  # stable canonical id (dedupe key together with recipient and event)
    event: str
    symbol: str
    side: int  # +1 BUY, -1 SELL
    timeframe: str  # the timeframe of the signal (primary or execution)
    primary_timeframe: str  # Strategy 4.3 timeframe (same as timeframe for 15m/30m/1h)
    execution_timeframe: str | None  # 1m / 5m / 10m when this is an execution confirmation
    entry: float
    stop: float
    targets: tuple[float, float, float]
    rr: tuple[float, float, float]
    tier: str
    score: float
    timing_score: float | None
    family_ar: str
    signal_time: int  # epoch s (confirmation candle close)
    price_precision: int | None = None
    test: bool = False
    extra: dict[str, str] = field(default_factory=dict)

    @property
    def side_text(self) -> str:
        return "BUY — شراء" if self.side == 1 else "SELL — بيع"


def _price(value: float, precision: int | None) -> str:
    if precision is None:
        precision = 2 if value >= 100 else 4 if value >= 1 else 6
    return f"{value:,.{max(0, precision)}f}"


def format_alert(a: SignalAlert) -> str:
    """The Telegram message text (plain text, Arabic labels, LTR numbers)."""
    p = a.price_precision
    when = datetime.fromtimestamp(a.signal_time, UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines: list[str] = []
    if a.test:
        lines += ["🧪 TEST — رسالة اختبار وليست إشارة حقيقية", ""]
    lines += [EVENT_TITLE.get(a.event, "Wese Trade"), ""]
    lines += ["العملة:", a.symbol, "", "الاتجاه:", a.side_text, ""]
    lines += ["الفريم الأساسي:", a.primary_timeframe, ""]
    if a.execution_timeframe:
        lines += ["توقيت الدخول:", a.execution_timeframe, ""]
    if a.event == "NEW":
        tier = f"{a.tier} — {TIER_AR[a.tier]}" if a.tier in TIER_AR else a.tier
        lines += ["جودة الفرصة:", tier, ""]
        lines += ["قوة الإشارة:", f"{round(a.score)} / 100", ""]
        if a.timing_score is not None:
            lines += ["قوة توقيت الدخول:", f"{round(a.timing_score)} / 100", ""]
        lines += ["نوع الفرصة:", a.family_ar, ""]
    lines += ["سعر الدخول:", _price(a.entry, p), ""]
    lines += ["وقف الخسارة:", _price(a.stop, p), ""]
    for n, t in enumerate(a.targets, start=1):
        lines += [f"TP{n}:", _price(t, p), ""]
    rr = " / ".join(f"{r:.1f}" for r in a.rr)
    lines += ["R:R:", f"1 : {a.rr[1]:.1f}  ({rr})", ""]
    lines += ["وقت الإشارة:", when]
    if a.event != "NEW":
        lines += ["", f"المعرّف: {a.signal_id}"]
    lines += ["", "تحليل وليس نصيحة مالية — التنفيذ يدوي."]
    return "\n".join(lines)
