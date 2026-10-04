"""MarketAnalyzer: the ONE canonical analysis implementation.

    analyzer = MarketAnalyzer("BTCUSDT", Timeframe.M5, tick_size=0.1)
    for candle in closed_candles:            # oldest first
        analyzer.update(candle)              # advances confirmed state by one candle
    snapshot = analyzer.snapshot(forming)    # read-only view (+ developing features)

No-repaint guarantee (tested in tests/analysis/test_no_lookahead.py):
* `update` processes CLOSED candles strictly in order; everything it emits at candle N is
  computed from candles <= N. Confirmed facts (pivots, BOS/CHoCH, sweeps, zone creation)
  are never moved or removed afterwards; zones/pools only advance their lifecycle.
* Batch analysis is the same loop, so "historical replay" and "live incremental" produce
  identical results by construction.
* The forming candle never mutates state: `snapshot(forming)` reports what holds with
  the forming candle as DEVELOPING features, recomputed from scratch on every call.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any

from app.analysis.config import DEFAULT_CONFIG, AnalysisConfig
from app.analysis.enums import (
    FeatureStatus,
    StructureDirection,
    StructureLayer,
    ZoneStatus,
)
from app.analysis.indicators.candles import candle_features
from app.analysis.indicators.state import IndicatorState
from app.analysis.liquidity.pools import LiquidityTracker
from app.analysis.models import (
    AnalysisSnapshot,
    DevelopingFeatures,
    FairValueGap,
    MtfFrame,
    MultiTimeframeContext,
    Pivot,
    StructureEvent,
    StructureState,
)
from app.analysis.regime.detector import detect_regime
from app.analysis.series import Bar, BarSeries, to_bar
from app.analysis.structure.displacement import displacement_score
from app.analysis.structure.market_structure import StructureTracker
from app.analysis.structure.pivots import PivotDetector
from app.analysis.zones.fvg import FvgTracker, detect_gap
from app.analysis.zones.order_blocks import OrderBlockTracker
from app.analysis.zones.ote import ote_zone
from app.analysis.zones.premium_discount import dealing_range, premium_discount
from app.market_data.models import Candle
from app.market_data.timeframes import Timeframe
from app.utils.time import utc_isoformat, utc_now


class AnalysisOrderError(ValueError):
    """A closed candle arrived out of order (the caller must re-seed the analyzer)."""


class MarketAnalyzer:
    def __init__(
        self,
        symbol: str,
        timeframe: Timeframe,
        *,
        tick_size: float | None = None,
        config: AnalysisConfig = DEFAULT_CONFIG,
    ) -> None:
        self.symbol = symbol
        self.timeframe = timeframe
        self.config = config
        self.tick = tick_size or 0.0
        self.series = BarSeries(config.max_bars_kept)
        self.indicators = IndicatorState(config)
        self.swing_pivots = PivotDetector(
            StructureLayer.SWING, config.swing_left, config.swing_right
        )
        self.internal_pivots = PivotDetector(
            StructureLayer.INTERNAL, config.internal_left, config.internal_right
        )
        self.swing = StructureTracker(StructureLayer.SWING, config.max_pivots_kept)
        self.internal = StructureTracker(
            StructureLayer.INTERNAL, config.max_pivots_kept, trailing=True
        )
        self.liquidity = LiquidityTracker(config, self.tick)
        self.fvgs = FvgTracker(config, self.tick)
        self.order_blocks = OrderBlockTracker(config, self.tick)
        self._relvol: deque[float | None] = deque(maxlen=3)
        self.rows: deque[dict[str, Any]] = deque(maxlen=config.history_rows)
        self.last_open_ms: int | None = None
        self.version = 0  # increments on every processed closed candle

    # --- confirmed state ------------------------------------------------------------------
    def update(self, candle: Candle) -> None:
        if not candle.is_closed:
            raise ValueError("MarketAnalyzer.update accepts closed candles only")
        if self.last_open_ms is not None and candle.open_ms <= self.last_open_ms:
            raise AnalysisOrderError(f"candle {candle.open_ms} not after {self.last_open_ms}")
        self.last_open_ms = candle.open_ms
        n = len(self.series)
        bar = to_bar(candle, n)
        self.series.append(bar)
        ind = self.indicators
        ind.update(bar)
        relvol = ind.relative_volume_at_last()
        self._relvol.append(relvol)
        atr, prev_atr = ind.atr_value, ind.prev_atr

        # 1) lifecycle of existing items with this candle
        self.liquidity.on_bar(bar, atr, relvol)
        self.fvgs.on_bar(bar)
        self.order_blocks.on_bar(bar, atr)

        # 2) pivots confirmed at this candle -> 3) structure
        swing_pivots = self.swing_pivots.update(self.series, n)
        internal_pivots = self.internal_pivots.update(self.series, n)
        for pivot in swing_pivots:
            self.swing.add_pivot(pivot, self.series)
        for pivot in internal_pivots:
            self.internal.add_pivot(pivot, self.series)

        def strength(b: Bar, move: float, bullish: bool) -> tuple[float, float | None, bool]:
            score = displacement_score(b, prev_atr, relvol, move, bullish, self.config)
            ok = relvol is not None and relvol >= self.config.breakout_volume_ratio
            return score, relvol, ok

        breaks = [
            r
            for r in (
                self.swing.on_bar(bar, self.series, strength),
                self.internal.on_bar(bar, self.series, strength),
            )
            if r is not None
        ]

        # 4) new liquidity from pivots, 5) sweep follow-up annotations
        for pivot in internal_pivots:
            self.liquidity.on_internal_pivot(pivot, atr)
        for pivot in swing_pivots:
            self.liquidity.on_swing_pivot(pivot, atr)
        self.liquidity.note_structure([r.event for r in breaks])

        # 6) fair value gap completed by this candle
        if n >= 2 and self.series.has(n - 2):
            c1, c2 = self.series.bar(n - 2), self.series.bar(n - 1)
            middle_relvol = self._relvol[-2] if len(self._relvol) >= 2 else None
            gap = detect_gap(
                c1,
                c2,
                bar,
                atr=prev_atr,
                tick=self.tick,
                config=self.config,
                displacement=self._candle_displacement(c2, prev_atr, middle_relvol),
                relative_volume=middle_relvol,
                structure=self.internal.direction,
            )
            if gap is not None:
                self.fvgs.add(gap)

        # 7) order blocks from this candle's structure breaks
        def candle_strength(b: Bar, bullish: bool) -> tuple[float, float | None]:
            return displacement_score(b, prev_atr, relvol, b.body, bullish, self.config), relvol

        for result in breaks:
            self.order_blocks.on_event(result.event, result.origin, self.series, candle_strength)

        self.version += 1
        self._record_row(bar)

    def _candle_displacement(self, bar: Bar, atr: float | None, relvol: float | None) -> float:
        bullish = bar.close >= bar.open
        return displacement_score(bar, atr, relvol, bar.body, bullish, self.config)

    def _record_row(self, bar: Bar) -> None:
        ind = self.indicators
        trend = ind.trend()
        vol = ind.volatility()
        row: dict[str, Any] = {
            "time": bar.time,
            "close": bar.close,
            "trend": trend.direction.value if trend else None,
            "trend_score": trend.score if trend else None,
            "rsi": ind.rsi.value,
            "atr_pct": vol.atr_pct if vol else None,
            "atr_percentile": vol.atr_percentile if vol else None,
            "volatility": vol.regime.value if vol else None,
            "relative_volume": self._relvol[-1] if self._relvol else None,
            "swing_structure": self.swing.direction.value,
            "internal_structure": self.internal.direction.value,
        }
        if trend is not None and vol is not None:
            regime = detect_regime(
                trend,
                self.swing.direction,
                ind.efficiency_ratio(),
                vol.regime,
                vol.atr_percentile,
                ind.range_compression(),
                self.config,
            )
            row["regime"] = regime.directional.value
        self.rows.append(row)

    # --- readiness --------------------------------------------------------------------------
    @property
    def candles(self) -> int:
        return len(self.series)

    def readiness(self) -> str | None:
        if len(self.series) < self.config.min_candles:
            return "insufficient_history"
        if not self.indicators.ready:
            return "indicators_warming_up"
        return None

    # --- context frame (confirmed only) ---------------------------------------------------------
    def frame(self) -> MtfFrame:
        ready = self.readiness() is None
        trend = self.indicators.trend() if ready else None
        vol = self.indicators.volatility() if ready else None
        regime = None
        if trend is not None and vol is not None:
            regime = detect_regime(
                trend,
                self.swing.direction,
                self.indicators.efficiency_ratio(),
                vol.regime,
                vol.atr_percentile,
                self.indicators.range_compression(),
                self.config,
            )
        return MtfFrame(
            timeframe=self.timeframe.value,
            ready=ready and trend is not None,
            candle_time=self.series.last.time if len(self.series) else None,
            trend=trend.direction if trend else None,
            structure=self.swing.direction if ready else None,
            directional_regime=regime.directional if regime else None,
            volatility_regime=vol.regime if vol else None,
        )

    # --- snapshot (read-only) ---------------------------------------------------------------------
    def snapshot(
        self,
        forming: Candle | None = None,
        *,
        context: list[MtfFrame] | None = None,
        generated_at: datetime | None = None,
        include_debug: bool = False,
    ) -> AnalysisSnapshot:
        generated = utc_isoformat(generated_at or utc_now())
        n = len(self.series)
        forming_bar: Bar | None = None
        if forming is not None and (
            self.last_open_ms is None or forming.open_ms > self.last_open_ms
        ):
            forming_bar = to_bar(forming, n)
        last = self.series.last if n else None
        price = forming_bar.close if forming_bar else last.close if last else None
        base: dict[str, Any] = {
            "symbol": self.symbol,
            "timeframe": self.timeframe.value,
            "candle_time": last.time if last else None,
            "forming_time": forming_bar.time if forming_bar else None,
            "price": price,
            "generated_at": generated,
            "candles_analyzed": n,
        }
        reason = self.readiness()
        trend = self.indicators.trend()
        vol = self.indicators.volatility()
        if reason is not None or trend is None or vol is None or last is None or price is None:
            return AnalysisSnapshot(
                analysis_ready=False, reason=reason or "indicators_warming_up", **base
            )
        cfg = self.config
        ind = self.indicators
        regime = detect_regime(
            trend,
            self.swing.direction,
            ind.efficiency_ratio(),
            vol.regime,
            vol.atr_percentile,
            ind.range_compression(),
            cfg,
        )
        atr = ind.atr_value
        prev = self.series.bar(n - 2) if self.series.has(n - 2) else None
        self.fvgs.refresh_quality(last.index)
        self.order_blocks.refresh_quality(last.index, atr)

        liquidity = self.liquidity.state(price)
        developing_fvgs: tuple[FairValueGap, ...] = ()
        developing = DevelopingFeatures()
        if forming_bar is not None:
            if prev is not None:
                gap = detect_gap(
                    prev,
                    last,
                    forming_bar,
                    atr=atr,
                    tick=self.tick,
                    config=cfg,
                    displacement=self._candle_displacement(last, atr, self._relvol[-1]),
                    relative_volume=self._relvol[-1],
                    structure=self.internal.direction,
                    status=FeatureStatus.DEVELOPING,
                )
                developing_fvgs = (gap,) if gap is not None else ()
            developing = DevelopingFeatures(
                swing_pivots=tuple(self.swing_pivots.developing(self.series, forming_bar)),
                internal_pivots=tuple(self.internal_pivots.developing(self.series, forming_bar)),
                swing_breaks=tuple(self.swing.developing(price)),
                internal_breaks=tuple(self.internal.developing(price)),
                sweeps=tuple(self.liquidity.developing(forming_bar)),
                fair_value_gaps=developing_fvgs,
            )

        rng = dealing_range(self.swing, self.series)
        if rng is None:
            rng = dealing_range(self.internal, self.series)
        pd = premium_discount(rng, price, cfg) if rng else None
        ote = ote_zone(rng, price, cfg) if rng else None

        mtf: MultiTimeframeContext | None = None
        if context is not None:
            from app.analysis.multi_timeframe.context import build_context

            mtf = build_context(self.frame(), context)

        fvgs = self._recent_zones(self.fvgs.gaps, last.index)
        blocks = self._recent_zones(self.order_blocks.blocks, last.index)
        return AnalysisSnapshot(
            analysis_ready=True,
            reason=None,
            **base,
            trend=trend,
            regime=regime,
            volatility=vol,
            momentum=ind.momentum(self._divergence()),
            volume=ind.volume(),
            candle=candle_features(last, prev, ind.prev_atr, FeatureStatus.CONFIRMED),
            forming_candle=(
                candle_features(forming_bar, last, atr, FeatureStatus.DEVELOPING)
                if forming_bar
                else None
            ),
            swing_structure=self._structure_state(self.swing),
            internal_structure=self._structure_state(self.internal),
            liquidity=liquidity,
            fair_value_gaps=tuple(fvgs),
            order_blocks=tuple(blocks),
            premium_discount=pd,
            ote=ote,
            multi_timeframe=mtf,
            developing=developing,
            counts=self.counts(),
            debug=self._debug(rng) if include_debug else None,
        )

    def _recent_zones(self, zones: list[Any], last_index: int) -> list[Any]:
        live = [z for z in zones if z.status in (ZoneStatus.ACTIVE, ZoneStatus.MITIGATED)]
        ended = [z for z in zones if z.status not in (ZoneStatus.ACTIVE, ZoneStatus.MITIGATED)]
        keep = self.config.output_zones
        recent_live = sorted(live, key=lambda z: z.created_index)[-keep:]
        return sorted([*recent_live, *ended[-5:]], key=lambda z: z.created_index)

    def _structure_state(self, tracker: StructureTracker) -> StructureState:
        up, down = tracker.up_level(), tracker.down_level()
        events = tracker.events[-self.config.output_events :]
        return StructureState(
            layer=tracker.layer,
            direction=tracker.direction,
            pivots=tuple(tracker.pivots[-self.config.output_pivots :]),
            events=tuple(events),
            last_event=tracker.events[-1] if tracker.events else None,
            protected_high=tracker.protected_high,
            protected_low=tracker.protected_low,
            break_high=up.price if up else None,
            break_low=down.price if down else None,
        )

    def _divergence(self) -> str | None:
        """Hook: regular RSI divergence between the last two internal pivots of a side."""
        rsi = self.indicators.rsi_by_index
        highs = [p for p in self.internal.pivots if p.side.value == "high"][-2:]
        lows = [p for p in self.internal.pivots if p.side.value == "low"][-2:]
        latest: tuple[int, str] | None = None
        if (
            len(highs) == 2
            and highs[0].index in rsi
            and highs[1].index in rsi
            and highs[1].price > highs[0].price
            and rsi[highs[1].index] < rsi[highs[0].index]
        ):
            latest = (highs[1].confirmed_index, "bearish")
        if (
            len(lows) == 2
            and lows[0].index in rsi
            and lows[1].index in rsi
            and lows[1].price < lows[0].price
            and rsi[lows[1].index] > rsi[lows[0].index]
            and (latest is None or lows[1].confirmed_index > latest[0])
        ):
            latest = (lows[1].confirmed_index, "bullish")
        if latest is None or len(self.series) - 1 - latest[0] > self.config.sweep_response_bars:
            return None
        return latest[1]

    def counts(self) -> dict[str, int]:
        live_fvgs = self.fvgs.active()
        return {
            "swing_pivots": self.swing_pivots.count,
            "internal_pivots": self.internal_pivots.count,
            "swing_bos": self.swing.counts["bos"],
            "swing_choch": self.swing.counts["choch"],
            "internal_bos": self.internal.counts["bos"],
            "internal_choch": self.internal.counts["choch"],
            "eqh": self.liquidity.counts["eqh"],
            "eql": self.liquidity.counts["eql"],
            "sweeps": self.liquidity.counts["sweeps"],
            "breakouts": self.liquidity.counts["breakouts"],
            "fvgs": self.fvgs.count,
            "active_fvgs": sum(1 for g in live_fvgs if g.status is ZoneStatus.ACTIVE),
            "mitigated_fvgs": sum(1 for g in live_fvgs if g.status is ZoneStatus.MITIGATED),
            "order_blocks": self.order_blocks.count,
            "active_order_blocks": len(self.order_blocks.active()),
        }

    def _debug(self, rng: Any) -> dict[str, Any]:
        def pivots(tracker: StructureTracker) -> list[dict[str, Any]]:
            return [
                {"index": p.index, "confirmed_index": p.confirmed_index, "type": p.type.value}
                for p in tracker.pivots[-8:]
            ]

        def levels(tracker: StructureTracker) -> dict[str, Any]:
            up, down = tracker.up_level(), tracker.down_level()
            return {
                "direction": tracker.direction.value,
                "break_high": up.price if up else None,
                "break_low": down.price if down else None,
                "protected_high": tracker.protected_high.price if tracker.protected_high else None,
                "protected_low": tracker.protected_low.price if tracker.protected_low else None,
            }

        return {
            "last_index": len(self.series) - 1,
            "first_kept_index": self.series.first_index,
            "swing": levels(self.swing),
            "internal": levels(self.internal),
            "swing_pivots": pivots(self.swing),
            "internal_pivots": pivots(self.internal),
            "dealing_range": None
            if rng is None
            else {"layer": rng.layer.value, "high": rng.high, "low": rng.low},
            "active_fvgs": len(self.fvgs.active()),
            "active_order_blocks": len(self.order_blocks.active()),
            "pivot_confirmation_bars": {
                "swing": self.config.swing_right,
                "internal": self.config.internal_right,
            },
        }

    # --- helpers for tests/replay ---------------------------------------------------------------
    def confirmed_facts(self) -> dict[str, list[Any]]:
        """Every immutable confirmed fact, for no-repaint comparisons."""
        return {
            "pivots": [*self.swing.pivots, *self.internal.pivots],
            "events": [*self.swing.events, *self.internal.events],
            "sweeps": [_sweep_fact(s) for s in self.liquidity.sweeps],
            "fvgs": [_zone_fact(g) for g in self.fvgs.gaps],
            "order_blocks": [_zone_fact(b) for b in self.order_blocks.blocks],
        }


def _sweep_fact(sweep: Any) -> tuple[Any, ...]:
    return (sweep.id, sweep.level, sweep.index, sweep.extreme, sweep.close, sweep.quality)


def _zone_fact(zone: Any) -> tuple[Any, ...]:
    return (zone.id, zone.type, zone.top, zone.bottom, zone.index, zone.confirmed_time)


def analyze_history(
    symbol: str,
    timeframe: Timeframe,
    candles: list[Candle],
    *,
    tick_size: float | None = None,
    config: AnalysisConfig = DEFAULT_CONFIG,
) -> tuple[MarketAnalyzer, Candle | None]:
    """Batch helper: feed closed candles; returns the analyzer and the forming candle."""
    analyzer = MarketAnalyzer(symbol, timeframe, tick_size=tick_size, config=config)
    forming = None
    for candle in candles:
        if candle.is_closed:
            analyzer.update(candle)
        else:
            forming = candle
    return analyzer, forming


__all__ = [
    "AnalysisOrderError",
    "MarketAnalyzer",
    "Pivot",
    "StructureDirection",
    "StructureEvent",
    "analyze_history",
]
