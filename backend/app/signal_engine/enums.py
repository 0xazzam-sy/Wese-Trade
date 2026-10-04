from __future__ import annotations

from enum import StrEnum


class SignalClass(StrEnum):
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


class Side(StrEnum):
    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> int:
        return 1 if self is Side.LONG else -1

    @property
    def direction(self) -> str:
        """Phase 3 direction string this side agrees with."""
        return "bullish" if self is Side.LONG else "bearish"

    @property
    def opposite(self) -> Side:
        return Side.SHORT if self is Side.LONG else Side.LONG


class SetupFamily(StrEnum):
    TREND_CONTINUATION = "TREND_CONTINUATION"
    PULLBACK_CONTINUATION = "PULLBACK_CONTINUATION"
    BREAKOUT_CONTINUATION = "BREAKOUT_CONTINUATION"
    LIQUIDITY_REVERSAL = "LIQUIDITY_REVERSAL"


class SignalState(StrEnum):
    DEVELOPING = "developing"  # forming-candle hypothesis; never a historical trade
    CONFIRMED = "confirmed"  # frozen at candle close; zone entry not filled yet
    ACTIVE = "active"  # entered
    TP1_HIT = "tp1_hit"
    TP2_HIT = "tp2_hit"
    TP3_HIT = "tp3_hit"  # final target: closed
    STOPPED = "stopped"
    INVALIDATED = "invalidated"  # setup broke before entry
    EXPIRED = "expired"  # zone never reached
    CLOSED = "closed"  # time stop / opposite signal / manual end

    @property
    def is_final(self) -> bool:
        return self in FINAL_STATES


FINAL_STATES = frozenset(
    {
        SignalState.TP3_HIT,
        SignalState.STOPPED,
        SignalState.INVALIDATED,
        SignalState.EXPIRED,
        SignalState.CLOSED,
    }
)


class EntryModel(StrEnum):
    MARKET = "MARKET_ENTRY"  # trigger candle close
    ZONE = "ZONE_ENTRY"  # limit at a retest level inside an entry zone


class ExitReason(StrEnum):
    TP3 = "tp3"
    STOP = "stop"
    TIME = "time_stop"
    OPPOSITE = "opposite_signal"
    END_OF_DATA = "end_of_data"
