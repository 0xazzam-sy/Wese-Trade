"""Fair value gaps (3-candle imbalance).

Bullish FVG at candles (c1, c2, c3): c3.low > c1.high; the gap is [c1.high, c3.low].
Bearish FVG: c3.high < c1.low; the gap is [c3.high, c1.low].
Known at c3's close. Kept only if size >= max(fvg_min_atr * ATR, fvg_min_ticks * tick),
with ATR taken BEFORE c3.

Lifecycle per later closed candle (forward-only):
  filled      = deepest share of the gap traded into (wicks count), 0..1
  mitigated   = filled >= fvg_mitigated_fill (price reached the midpoint)
  invalidated = a CLOSE beyond the far edge (below the bottom of a bullish gap)
  expired     = older than fvg_max_age bars
"""

from __future__ import annotations

from app.analysis.config import AnalysisConfig
from app.analysis.enums import FeatureStatus, StructureDirection, ZoneStatus, ZoneType
from app.analysis.models import FairValueGap
from app.analysis.scoring.feature_quality import fvg_quality
from app.analysis.series import Bar

KEEP_ENDED_BARS = 150


def detect_gap(
    c1: Bar,
    c2: Bar,
    c3: Bar,
    *,
    atr: float | None,
    tick: float,
    config: AnalysisConfig,
    displacement: float,
    relative_volume: float | None,
    structure: StructureDirection,
    status: FeatureStatus = FeatureStatus.CONFIRMED,
) -> FairValueGap | None:
    if not atr:
        return None
    minimum = max(config.fvg_min_atr * atr, config.fvg_min_ticks * tick)
    if c3.low > c1.high and c3.low - c1.high >= minimum:
        kind, top, bottom = ZoneType.BULLISH_FVG, c3.low, c1.high
        aligned = structure is StructureDirection.BULLISH
    elif c3.high < c1.low and c1.low - c3.high >= minimum:
        kind, top, bottom = ZoneType.BEARISH_FVG, c1.low, c3.high
        aligned = structure is StructureDirection.BEARISH
    else:
        return None
    return FairValueGap(
        id=f"fvg:{kind.value}:{c2.time}",
        type=kind,
        top=top,
        bottom=bottom,
        index=c2.index,
        time=c2.time,
        created_index=c3.index,
        confirmed_time=c3.close_time,
        size_atr=(top - bottom) / atr,
        displacement=displacement,
        relative_volume=relative_volume,
        aligned=aligned,
        status_detail=status,
    )


class FvgTracker:
    def __init__(self, config: AnalysisConfig, tick: float) -> None:
        self.config = config
        self.tick = tick
        self.gaps: list[FairValueGap] = []
        self.count = 0

    def add(self, gap: FairValueGap) -> None:
        self.gaps.append(gap)
        self.count += 1

    def on_bar(self, bar: Bar) -> None:
        cfg = self.config
        for gap in self.gaps:
            if gap.status in (ZoneStatus.INVALIDATED, ZoneStatus.EXPIRED):
                continue
            if bar.index - gap.created_index > cfg.fvg_max_age:
                gap.status, gap.ended_time = ZoneStatus.EXPIRED, bar.close_time
                continue
            bullish = gap.type is ZoneType.BULLISH_FVG
            if bullish and bar.low < gap.top:
                gap.filled = max(gap.filled, min(1.0, (gap.top - bar.low) / gap.size))
            elif not bullish and bar.high > gap.bottom:
                gap.filled = max(gap.filled, min(1.0, (bar.high - gap.bottom) / gap.size))
            if (bullish and bar.close < gap.bottom) or (not bullish and bar.close > gap.top):
                gap.status, gap.ended_time = ZoneStatus.INVALIDATED, bar.close_time
                gap.status_detail = FeatureStatus.INVALIDATED
            elif gap.status is ZoneStatus.ACTIVE and gap.filled >= cfg.fvg_mitigated_fill:
                gap.status, gap.mitigated_time = ZoneStatus.MITIGATED, bar.close_time
        cutoff = bar.index - KEEP_ENDED_BARS
        self.gaps = [
            g
            for g in self.gaps
            if g.status in (ZoneStatus.ACTIVE, ZoneStatus.MITIGATED) or g.created_index > cutoff
        ]

    def refresh_quality(self, last_index: int) -> None:
        for gap in self.gaps:
            gap.quality = fvg_quality(
                gap.size_atr,
                gap.displacement,
                gap.relative_volume,
                gap.aligned,
                last_index - gap.created_index,
                gap.status,
                gap.filled,
            )

    def active(self) -> list[FairValueGap]:
        return [g for g in self.gaps if g.status in (ZoneStatus.ACTIVE, ZoneStatus.MITIGATED)]
