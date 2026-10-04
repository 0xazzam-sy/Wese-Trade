"""Order blocks — created only from a confirmed BOS/CHoCH with displacement.

Bullish OB (from a bullish break at candle b whose move started at the leg's lowest low,
candle m):
  * the LAST bearish candle (close < open) at or before m, searching back at most
    `ob_search_bars` candles, merged with up to `ob_max_cluster - 1` immediately
    preceding consecutive bearish candles;
  * zone = [min(cluster lows, low of m), max(cluster highs)];
  * required: the strongest candle in (m, b] has displacement >= ob_min_displacement.
Bearish OB mirrors this. If no qualifying candle exists, no OB is created.

Lifecycle per later closed candle (forward-only):
  touch       = price trades back into the zone after being outside it
  mitigated   = first touch (zone still valid)
  invalidated = CLOSE beyond the far edge by more than
                max(ob_invalidation_atr * ATR, ob_invalidation_min_ticks * tick)
  expired     = older than ob_max_age bars
"""

from __future__ import annotations

from collections.abc import Callable

from app.analysis.config import AnalysisConfig
from app.analysis.enums import StructureDirection, StructureLayer, ZoneStatus, ZoneType
from app.analysis.models import OrderBlock, StructureEvent
from app.analysis.scoring.feature_quality import order_block_quality
from app.analysis.series import Bar, BarSeries

KEEP_ENDED_BARS = 150

# (bar, bullish) -> (displacement score, relative volume)
CandleStrength = Callable[[Bar, bool], tuple[float, float | None]]


class OrderBlockTracker:
    def __init__(self, config: AnalysisConfig, tick: float) -> None:
        self.config = config
        self.tick = tick
        self.blocks: list[OrderBlock] = []
        self.count = 0

    def on_event(
        self,
        event: StructureEvent,
        origin: Bar,
        series: BarSeries,
        strength: CandleStrength,
    ) -> OrderBlock | None:
        cfg = self.config
        bullish = event.direction is StructureDirection.BULLISH
        # Displacement requirement: strongest candle of the leg (origin, break].
        leg = series.window(origin.index + 1, event.index)
        if not leg:
            return None
        scored = [(strength(b, bullish), b) for b in leg]
        (best, relvol), _ = max(scored, key=lambda item: item[0][0])
        if best < cfg.ob_min_displacement:
            return None

        def opposite(b: Bar) -> bool:
            return b.bearish if bullish else b.bullish

        end: Bar | None = None
        for bar in reversed(series.window(origin.index - cfg.ob_search_bars, origin.index)):
            if opposite(bar):
                end = bar
                break
        if end is None:
            return None
        cluster = [end]
        for bar in reversed(series.window(end.index - cfg.ob_max_cluster + 1, end.index - 1)):
            if not opposite(bar):
                break
            cluster.insert(0, bar)
        if bullish:
            top = max(b.high for b in cluster)
            bottom = min(min(b.low for b in cluster), origin.low)
        else:
            top = max(max(b.high for b in cluster), origin.high)
            bottom = min(b.low for b in cluster)
        kind = ZoneType.BULLISH_OB if bullish else ZoneType.BEARISH_OB
        start = cluster[0]
        for existing in self.blocks:
            if existing.type is kind and existing.index == start.index:
                if event.layer is StructureLayer.SWING:
                    existing.layer = StructureLayer.SWING  # same block, now swing-relevant
                return None
        block = OrderBlock(
            id=f"ob:{kind.value}:{start.time}",
            type=kind,
            top=top,
            bottom=bottom,
            index=start.index,
            time=start.time,
            end_index=end.index,
            created_index=event.index,
            confirmed_time=event.confirmed_time,
            source_event_id=event.id,
            layer=event.layer,
            displacement=best,
            relative_volume=relvol,
        )
        self.blocks.append(block)
        self.count += 1
        return block

    def on_bar(self, bar: Bar, atr: float | None) -> None:
        cfg = self.config
        tol = max(
            cfg.ob_invalidation_atr * atr if atr else 0.0, cfg.ob_invalidation_min_ticks * self.tick
        )
        for block in self.blocks:
            if not block.active or bar.index <= block.created_index:
                continue
            if bar.index - block.created_index > cfg.ob_max_age:
                block.status, block.ended_time = ZoneStatus.EXPIRED, bar.close_time
                continue
            bullish = block.type is ZoneType.BULLISH_OB
            if (bullish and bar.close < block.bottom - tol) or (
                not bullish and bar.close > block.top + tol
            ):
                block.status, block.ended_time = ZoneStatus.INVALIDATED, bar.close_time
                continue
            inside = bar.low <= block.top if bullish else bar.high >= block.bottom
            if inside and not block.inside:
                block.touches += 1
                if block.status is ZoneStatus.ACTIVE:
                    block.status, block.mitigated_time = ZoneStatus.MITIGATED, bar.close_time
            block.inside = inside
        cutoff = bar.index - KEEP_ENDED_BARS
        self.blocks = [b for b in self.blocks if b.active or b.created_index > cutoff]

    def refresh_quality(self, last_index: int, atr: float | None) -> None:
        for block in self.blocks:
            height = (block.top - block.bottom) / atr if atr else None
            block.quality = order_block_quality(
                block.displacement,
                block.relative_volume,
                block.layer,
                height,
                last_index - block.created_index,
                block.touches,
                block.status,
            )

    def active(self) -> list[OrderBlock]:
        return [b for b in self.blocks if b.active]
