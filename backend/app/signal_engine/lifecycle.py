"""SignalTracker: cooldown, dedupe, confirmation and lifecycle — shared by live and backtest.

Execution order for each CLOSED candle t (explicit, no lookahead):
  1. `on_bar(bar_t)`: advance the open signal with candle t's OHLC (it can only react to
     prices printed AFTER its confirmation candle).
  2. `on_evaluation(eval_t, bar_t)`: a trade evaluation confirmed at t's close may open a
     new signal. Its plan is frozen here; candle t is never used for its fills/exits.

Fills and exits (long; short mirrors):
  MARKET_ENTRY  filled at the confirmation candle close (+ slippage in net R).
  ZONE_ENTRY    pending; filled when a later candle's low <= preferred entry. On the fill
                candle only the stop is checked (the TP side of the range may have printed
                BEFORE the fill, so it is never credited). A close below the invalidation
                level before the fill -> INVALIDATED; no fill within entry_expiry_bars -> EXPIRED.
  Stop          low <= stop (a gap below the stop exits at the open — worse).
  Targets       high >= TPk; each target closes its fraction (1/3 by default).
  SAME CANDLE   stop AND an unhit target both inside one candle: the intrabar order is
                unknowable from OHLC, so the STOP is assumed first (conservative) and the
                signal is flagged `ambiguous` (reported separately).
  Time stop     still open after max_hold_bars -> remainder closed at that candle's close.
  Opposite      a new STRONG opposite signal (if allowed) closes the remainder at close.
R accounting
  risk = |preferred_entry - stop| (planned). gross R uses planned prices; net R adds
  slippage on market entries and stop/time/opposite exits, taker fees on those and maker
  fees on limit entries and take-profits. Outcomes are R-multiples, never account P&L.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable

from app.analysis.series import Bar
from app.signal_engine.config import SignalConfig
from app.signal_engine.enums import (
    EntryModel,
    ExitReason,
    Side,
    SignalClass,
    SignalState,
)
from app.signal_engine.models import Signal, SignalEvaluation

EventSink = Callable[[str, Signal], None]  # ("confirmed" | "updated" | "closed", signal)
STRONG = {SignalClass.STRONG_BUY, SignalClass.STRONG_SELL}


def signal_id(symbol: str, timeframe: str, family: str, side: str, trigger_id: str) -> str:
    raw = f"{symbol}|{timeframe}|{family}|{side}|{trigger_id}"
    return f"{symbol}-{timeframe}-{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


class SignalTracker:
    def __init__(
        self,
        symbol: str,
        timeframe: str,
        config: SignalConfig,
        *,
        step_seconds: int,
        sink: EventSink | None = None,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.config = config
        self.step = step_seconds
        self.sink = sink or (lambda _kind, _signal: None)
        self.active: Signal | None = None
        self.closed: list[Signal] = []
        self.keep_closed = True
        self._last_confirmed: dict[Side, tuple[int, SignalClass]] = {}
        self._seen: set[str] = set()
        self.suppressed: dict[str, int] = {}

    # --- dedupe across restarts ------------------------------------------------------------
    def remember(self, ids: set[str]) -> None:
        self._seen |= ids

    def restore(self, signals: list[Signal]) -> None:
        """Rebuild state after a restart from persisted signals of this stream (oldest
        first): seen ids (dedupe), last confirmation per side (cooldown) and the open
        signal. Behaviour afterwards is identical to an uninterrupted tracker."""
        for s in signals:
            self._seen.add(s.id)
            self._last_confirmed[s.side] = (s.confirmed_time, s.signal_class)
            if not s.state.is_final:
                self.active = s

    # --- confirmation --------------------------------------------------------------------------
    def on_evaluation(self, ev: SignalEvaluation, bar: Bar) -> Signal | None:
        if ev.developing or not ev.is_trade or ev.hypothesis is None or ev.plan is None:
            return None
        hyp, plan = ev.hypothesis, ev.plan
        if ev.side is None:
            return None
        sid = signal_id(
            self.symbol, self.timeframe, hyp.family.value, ev.side.value, hyp.trigger.id
        )
        if sid in self._seen:
            return self._suppress("duplicate")
        cfg = self.config
        last = self._last_confirmed.get(ev.side)
        if last is not None and (bar.close_time - last[0]) // self.step < cfg.cooldown_bars:
            return self._suppress("cooldown")
        opposite = self._last_confirmed.get(ev.side.opposite)
        strong = ev.signal_class in STRONG
        recent_opposite = (
            opposite is not None and (bar.close_time - opposite[0]) // self.step < cfg.cooldown_bars
        )
        if recent_opposite and not (strong and cfg.allow_opposite_strong_override):
            return self._suppress("cooldown_opposite")
        if self.active is not None:
            if self.active.side is ev.side:
                return self._suppress("active_same_side")
            if not (strong and cfg.allow_opposite_strong_override):
                return self._suppress("active_opposite")
            self._exit_all(self.active, bar.close, bar.close_time, ExitReason.OPPOSITE, market=True)
            self._close(self.active, SignalState.CLOSED, bar.close_time)
        signal = Signal(
            id=sid,
            symbol=self.symbol,
            timeframe=self.timeframe,
            side=ev.side,
            signal_class=ev.signal_class,
            family=hyp.family,
            score=hyp.score,
            trigger_id=hyp.trigger.id,
            trigger_time=bar.time,
            confirmed_time=bar.close_time,
            plan=plan,
            components=hyp.components,
            penalties=hyp.penalties,
            positive=hyp.positive,
            negative=hyp.negative,
            evidence=ev.evidence,
            strategy_version=ev.strategy_version,
            regime=hyp.regime,
            state_time=bar.close_time,
        )
        signal.history.append((bar.close_time, SignalState.CONFIRMED.value))
        self._seen.add(sid)
        self._last_confirmed[ev.side] = (bar.close_time, ev.signal_class)
        if plan.entry_model is EntryModel.MARKET:
            self._enter(signal, plan.preferred_entry, bar.close_time, market=True)
        self.active = signal
        self.sink("confirmed", signal)
        return signal

    def _suppress(self, why: str) -> Signal | None:
        self.suppressed[why] = self.suppressed.get(why, 0) + 1
        return None

    # --- lifecycle --------------------------------------------------------------------------
    def on_bar(self, bar: Bar) -> None:
        s = self.active
        if s is None or bar.close_time <= s.confirmed_time:
            return
        changed = self._advance(s, bar)
        if s.state.is_final:
            self.active = None
            self.sink("closed", s)
        elif changed:
            self.sink("updated", s)

    def _advance(self, s: Signal, bar: Bar) -> bool:
        cfg, plan, sign = self.config, s.plan, s.side.sign
        before = (s.state, s.targets_hit)
        if not s.entered:
            s.bars_pending += 1
            touched = (
                (bar.low <= plan.preferred_entry)
                if sign > 0
                else (bar.high >= plan.preferred_entry)
            )
            if touched:
                fill = plan.preferred_entry
                opened_beyond = (bar.open < fill) if sign > 0 else (bar.open > fill)
                if opened_beyond:
                    fill = bar.open  # gapped through the limit: filled at the (better) open
                self._enter(s, fill, bar.close_time, market=False)
                s.bars_held = 1
                if self._stop_hit(s, bar):
                    self._exit_all(
                        s, self._stop_price(s, bar), bar.close_time, ExitReason.STOP, market=True
                    )
                    self._close(s, SignalState.STOPPED, bar.close_time)
                return True
            closed_beyond = (
                (bar.close < plan.invalidation) if sign > 0 else (bar.close > plan.invalidation)
            )
            if closed_beyond:
                self._close(s, SignalState.INVALIDATED, bar.close_time)
            elif s.bars_pending >= cfg.entry_expiry_bars:
                self._close(s, SignalState.EXPIRED, bar.close_time)
            return (s.state, s.targets_hit) != before

        s.bars_held += 1
        self._track_excursion(s, bar)
        stop_hit = self._stop_hit(s, bar)
        hits = []
        for k in range(s.targets_hit, 3):
            tp = plan.targets[k].price
            if (bar.high >= tp) if sign > 0 else (bar.low <= tp):
                hits.append(k)
            else:
                break
        if stop_hit and hits:
            s.ambiguous = True  # order unknowable inside one candle: assume the stop first
            hits = []
        for k in hits:
            fraction = cfg.target_fractions[k]
            s.exits.append((fraction, plan.targets[k].price, f"tp{k + 1}"))
            s.remaining -= fraction
            s.targets_hit = k + 1
            state = (SignalState.TP1_HIT, SignalState.TP2_HIT, SignalState.TP3_HIT)[k]
            self._set(s, state, bar.close_time)
        if s.targets_hit == 3:
            s.remaining = 0.0
            s.exit_reason = ExitReason.TP3
            self._finish(s, bar.close_time)
            return True
        if stop_hit:
            self._exit_all(
                s, self._stop_price(s, bar), bar.close_time, ExitReason.STOP, market=True
            )
            self._close(s, SignalState.STOPPED, bar.close_time)
        elif s.bars_held >= cfg.max_hold_bars:
            self._exit_all(s, bar.close, bar.close_time, ExitReason.TIME, market=True)
            self._close(s, SignalState.CLOSED, bar.close_time)
        return (s.state, s.targets_hit) != before

    def _current_stop(self, s: Signal) -> float:
        if self.config.move_stop_to_entry_after_tp1 and s.targets_hit >= 1:
            return s.plan.preferred_entry
        return s.plan.stop

    def _stop_hit(self, s: Signal, bar: Bar) -> bool:
        stop = self._current_stop(s)
        return bar.low <= stop if s.side is Side.LONG else bar.high >= stop

    def _stop_price(self, s: Signal, bar: Bar) -> float:
        stop = self._current_stop(s)
        if s.side is Side.LONG:
            return min(stop, bar.open)
        return max(stop, bar.open)

    def _track_excursion(self, s: Signal, bar: Bar) -> None:
        risk = s.plan.risk or 1e-12
        entry = s.entry_price or s.plan.preferred_entry
        favorable = (bar.high - entry) if s.side is Side.LONG else (entry - bar.low)
        adverse = (entry - bar.low) if s.side is Side.LONG else (bar.high - entry)
        s.mfe_r = max(s.mfe_r, favorable / risk)
        s.mae_r = max(s.mae_r, adverse / risk)

    # --- transitions ----------------------------------------------------------------------------
    def _enter(self, s: Signal, price: float, when: int, *, market: bool) -> None:
        s.entered_time = when
        s.entry_price = price
        s.evidence = {**s.evidence, "entry_market": market}
        self._set(s, SignalState.ACTIVE, when)

    def _exit_all(
        self, s: Signal, price: float, when: int, why: ExitReason, *, market: bool
    ) -> None:
        if s.remaining > 1e-9 and s.entered:
            s.exits.append((s.remaining, price, why.value + (":market" if market else "")))
            s.remaining = 0.0
        s.exit_reason = why

    def _close(self, s: Signal, state: SignalState, when: int) -> None:
        self._set(s, state, when)
        self._finish(s, when)

    def _set(self, s: Signal, state: SignalState, when: int) -> None:
        s.state = state
        s.state_time = when
        s.history.append((when, state.value))

    def _finish(self, s: Signal, when: int) -> None:
        s.closed_time = when
        if s.state is not SignalState.TP3_HIT and not s.state.is_final:
            self._set(s, SignalState.CLOSED, when)
        compute_r(s, self.config)
        if self.keep_closed:
            self.closed.append(s)

    def finish_open(self, when: int, price: float) -> None:
        """End of data (backtest only): close the open signal, marked END_OF_DATA."""
        s = self.active
        if s is None:
            return
        if s.entered:
            self._exit_all(s, price, when, ExitReason.END_OF_DATA, market=True)
        self._close(s, SignalState.CLOSED if s.entered else SignalState.EXPIRED, when)
        self.active = None


def compute_r(s: Signal, cfg: SignalConfig) -> None:
    if not s.entered or s.entry_price is None:
        s.gross_r = s.net_r = None
        return
    plan, sign = s.plan, s.side.sign
    risk = abs(plan.preferred_entry - plan.stop)
    if risk <= 0:
        s.gross_r = s.net_r = 0.0
        return
    market_entry = bool(s.evidence.get("entry_market"))
    fill = s.entry_price
    # Entry: market orders pay adverse slippage + taker fee; limit entries pay maker fee.
    entry_price_net = fill * (1 + sign * cfg.slippage_rate) if market_entry else fill
    entry_fee = (cfg.fee_rate if market_entry else cfg.maker_fee_rate) * fill
    gross = net = 0.0
    for fraction, price, why in s.exits:
        gross += fraction * sign * (price - plan.preferred_entry) / risk
        take_profit = why.startswith("tp")
        # Exit: take-profits are limit orders (maker, no slippage); stops/time/opposite are
        # market orders (adverse slippage + taker fee).
        exit_price_net = price if take_profit else price * (1 - sign * cfg.slippage_rate)
        exit_fee = (cfg.maker_fee_rate if take_profit else cfg.fee_rate) * price
        pnl = sign * (exit_price_net - entry_price_net) - entry_fee - exit_fee
        net += fraction * pnl / risk
    s.gross_r = round(gross, 4)
    s.net_r = round(net, 4)
