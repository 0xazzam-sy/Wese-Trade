"""Arabic reason texts. Every signal explains itself: no black-box output."""

from __future__ import annotations

from app.signal_engine.enums import SetupFamily, Side

TF_AR = {"1m": "1د", "5m": "5د", "10m": "10د", "15m": "15د", "30m": "30د", "1h": "1س"}
DIR_AR = {"bullish": "صاعد", "bearish": "هابط", "neutral": "محايد"}

FAMILY_AR = {
    SetupFamily.TREND_CONTINUATION: "استمرار الاتجاه",
    SetupFamily.PULLBACK_CONTINUATION: "استمرار بعد تصحيح",
    SetupFamily.BREAKOUT_CONTINUATION: "استمرار بعد اختراق",
    SetupFamily.LIQUIDITY_REVERSAL: "انعكاس بعد سحب سيولة",
}


def side_word(side: Side) -> str:
    return "صاعد" if side is Side.LONG else "هابط"


def tf(timeframe: str) -> str:
    return TF_AR.get(timeframe, timeframe)


def htf_aligned(frames: list[str], side: Side) -> str:
    return f"اتجاه {' و'.join(tf(f) for f in frames)} {side_word(side)}"


def htf_opposed(frame: str, direction: str) -> str:
    return f"تعارض مع اتجاه {tf(frame)} {DIR_AR.get(direction, direction)}"


def structure_event(layer: str, kind: str, side: Side) -> str:
    name = "CHoCH" if kind == "CHOCH" else "BOS"
    where = "داخلي" if layer == "internal" else "رئيسي"
    return f"{name} {where} {side_word(side)} مؤكد"


SWEEP_FOR = {
    Side.LONG: "تم سحب سيولة بيعية (تحت القيعان) ثم الارتداد",
    Side.SHORT: "تم سحب سيولة شرائية (فوق القمم) ثم الارتداد",
}
ADVERSE_SWEEP = {
    Side.LONG: "سحب سيولة علوية حديث يدل على رفض للأعلى",
    Side.SHORT: "سحب سيولة سفلية حديث يدل على رفض للأسفل",
}
