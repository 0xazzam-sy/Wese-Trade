"""Lower-timeframe execution study: does 5m timing improve entries of 15m/30m setups?

The trade THESIS stays the higher-timeframe signal (its stop and targets are unchanged).
Only the entry moment changes, and only using information available at that moment:

  A5  enter at the HTF confirmation close, then manage the trade on 5m bars.
  D5  after the HTF confirmation close T, wait for the FIRST 5m internal CHoCH in the
      trade direction that is confirmed strictly after T (a 5m pullback that recovered);
      enter at that 5m candle's close. Cancelled if, before the fill, a 5m candle closes
      beyond the HTF stop or trades through TP1 (the move left without us), or if no
      CHoCH appears within the HTF entry-expiry window.

Both are managed on the same 5m path with the tracker's rules (stop first when stop and a
target share a candle, gaps through the stop exit at the open, 1/3 per target, time stop
of 48 HTF bars) and the same cost model (`compute_r`). Comparing A5 vs D5 isolates the
effect of the 5m timing.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass, replace

from app.analysis.series import Bar
from app.market_data.timeframes import Timeframe
from app.research.collect import SeriesResearch
from app.signal_engine.config import SignalConfig
from app.signal_engine.enums import EntryModel, ExitReason, Side, SignalState
from app.signal_engine.lifecycle import compute_r
from app.signal_engine.models import Signal


@dataclass(frozen=True, slots=True)
class LtfEvent:
    close_time: int
    bar_index: int
    direction: str  # bullish | bearish


def choch_events(ltf: SeriesResearch, kinds: tuple[str, ...] = ("CHOCH",)) -> list[LtfEvent]:
    """Internal structure events confirmed on each 5m candle (from the recorded triggers)."""
    out = []
    for t in ltf.triggers:
        for layer, kind, direction in t.events:
            if layer == "internal" and kind in kinds:
                out.append(LtfEvent(t.close_time, t.index, direction))
    return out


def manage(
    signal: Signal, bars: Sequence[Bar], start: int, fill: float, end_time: int, cfg: SignalConfig
) -> Signal:
    """Manage an entered trade on `bars[start:]` (bars strictly after the fill)."""
    s = replace(signal, exits=[], remaining=1.0, targets_hit=0, ambiguous=False, history=[])
    plan = replace(s.plan, preferred_entry=fill, risk=abs(fill - s.plan.stop))
    s.plan = plan
    s.entry_price = fill
    s.entered_time = bars[start - 1].close_time if start > 0 else signal.confirmed_time
    s.evidence = {**s.evidence, "entry_market": True}
    sign = s.side.sign
    for bar in bars[start:]:
        stop_hit = bar.low <= plan.stop if sign > 0 else bar.high >= plan.stop
        hits = []
        for k in range(s.targets_hit, 3):
            tp = plan.targets[k].price
            if (bar.high >= tp) if sign > 0 else (bar.low <= tp):
                hits.append(k)
            else:
                break
        if stop_hit and hits:
            s.ambiguous = True
            hits = []
        for k in hits:
            s.exits.append((cfg.target_fractions[k], plan.targets[k].price, f"tp{k + 1}"))
            s.remaining -= cfg.target_fractions[k]
            s.targets_hit = k + 1
        if s.targets_hit == 3:
            s.remaining, s.exit_reason, s.state = 0.0, ExitReason.TP3, SignalState.TP3_HIT
            break
        if stop_hit:
            price = min(plan.stop, bar.open) if sign > 0 else max(plan.stop, bar.open)
            s.exits.append((s.remaining, price, "stop:market"))
            s.remaining, s.exit_reason, s.state = 0.0, ExitReason.STOP, SignalState.STOPPED
            break
        if bar.close_time >= end_time:
            s.exits.append((s.remaining, bar.close, "time:market"))
            s.remaining, s.exit_reason, s.state = 0.0, ExitReason.TIME, SignalState.CLOSED
            break
    else:
        if s.remaining > 1e-9 and bars:
            s.exits.append((s.remaining, bars[-1].close, "end_of_data:market"))
            s.remaining, s.exit_reason, s.state = 0.0, ExitReason.END_OF_DATA, SignalState.CLOSED
    compute_r(s, cfg)
    return s


def ltf_entries(
    signals: Sequence[Signal],
    ltf: SeriesResearch,
    htf: Timeframe,
    cfg: SignalConfig,
    *,
    pullback_levels: dict[int, float] | None = None,
) -> tuple[list[Signal], list[Signal], dict[str, int]]:
    """(A5 trades, D5 trades, counts) for HTF signals that were entered at market.

    Default D5: first aligned 5m internal CHoCH confirmed after T.
    With `pullback_levels` ({confirmation close time: HTF confirmation-candle midpoint}):
    first wait for a 5m candle trading back to that midpoint, THEN take the first aligned
    5m internal BOS or CHoCH confirmed after that pullback candle (internal recovery).
    """
    bars = ltf.bars
    closes = [b.close_time for b in bars]
    events = choch_events(ltf, ("CHOCH",) if pullback_levels is None else ("CHOCH", "BOS"))
    ev_times = [e.close_time for e in events]
    expiry = cfg.entry_expiry_bars * htf.seconds
    hold = cfg.max_hold_bars * htf.seconds
    a5: list[Signal] = []
    d5: list[Signal] = []
    counts = {
        "htf_signals": 0,
        "no_ltf_data": 0,
        "d_filled": 0,
        "d_no_choch": 0,
        "d_cancel_stop": 0,
        "d_cancel_tp1": 0,
    }
    for sig in signals:
        if not sig.entered or sig.entry_price is None:
            continue
        if sig.plan.entry_model is not EntryModel.MARKET:
            counts["skipped_zone_entry"] += 1  # thesis already uses a limit entry
            continue
        counts["htf_signals"] += 1
        t = sig.confirmed_time
        start = bisect_right(closes, t)  # first 5m bar CLOSING after T
        if start >= len(bars) or start == 0 or closes[start - 1] != t:
            counts["no_ltf_data"] += 1
            continue
        a5.append(manage(sig, bars, start, sig.plan.preferred_entry, t + hold, cfg))
        sign = sig.side.sign
        want = "bullish" if sig.side is Side.LONG else "bearish"
        after_t = t
        if pullback_levels is not None:
            level = pullback_levels.get(t)
            pulled = None
            for b in bars[start:]:
                if b.close_time > t + expiry:
                    break
                if (b.low <= level) if sign > 0 else (b.high >= level):  # type: ignore[operator]
                    pulled = b
                    break
            if level is None or pulled is None:
                counts["d_no_choch"] += 1
                continue
            after_t = pulled.close_time - 1  # an event on the pullback candle itself counts
        k = bisect_right(ev_times, after_t)  # events confirmed strictly after T
        fill_index = None
        while k < len(events) and events[k].close_time <= t + expiry:
            if events[k].direction == want:
                fill_index = events[k].bar_index
                break
            k += 1
        if fill_index is None:
            counts["d_no_choch"] += 1
            continue
        cancelled = None
        for b in bars[start : fill_index + 1]:
            if (b.close < sig.plan.stop) if sign > 0 else (b.close > sig.plan.stop):
                cancelled = "d_cancel_stop"
                break
            tp1 = sig.plan.targets[0].price
            if (b.high >= tp1) if sign > 0 else (b.low <= tp1):
                cancelled = "d_cancel_tp1"
                break
        if cancelled:
            counts[cancelled] += 1
            continue
        fill = bars[fill_index].close
        if sign * (fill - sig.plan.stop) <= 0:
            counts["d_cancel_stop"] += 1
            continue
        counts["d_filled"] += 1
        d5.append(manage(sig, bars, fill_index + 1, fill, t + hold, cfg))
    return a5, d5, counts
