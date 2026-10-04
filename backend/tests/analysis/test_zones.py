"""FVG, order blocks, premium/discount, OTE."""

from __future__ import annotations

from dataclasses import replace

import pytest

from app.analysis.enums import (
    FeatureStatus,
    PremiumDiscountZone,
    StructureDirection,
    StructureLayer,
    ZoneStatus,
    ZoneType,
)
from app.analysis.models import FairValueGap
from app.analysis.zones.ote import ote_zone
from app.analysis.zones.premium_discount import DealingRange, dealing_range, premium_discount
from tests.analysis.helpers import SMALL, ohlc, run, zigzag

FVG_ROWS: list[tuple[float, float, float, float]] = [
    (100, 101, 99, 100),
    (100, 101, 99.5, 100.5),
    (100.5, 101, 99.8, 100.8),  # c1: high 101
    (100.8, 108, 100.7, 107.8),  # c2: displacement
    (107.8, 109, 103, 108.5),  # c3: low 103 -> bullish gap [101, 103]
]


Row = tuple[float, float, float, float]


def _gap(rows: list[Row]) -> FairValueGap:
    gaps = run(ohlc(rows)).fvgs.gaps
    assert len(gaps) == 1
    return gaps[0]


def test_bullish_fvg_detection() -> None:
    gap = _gap(FVG_ROWS)
    assert gap.type is ZoneType.BULLISH_FVG
    assert (gap.bottom, gap.top, gap.mid, gap.size) == (101, 103, 102, 2)
    assert gap.index == 3 and gap.created_index == 4  # anchored to c2, known at c3's close
    assert gap.status is ZoneStatus.ACTIVE and gap.filled == 0
    assert gap.size_atr > 0 and 0 <= gap.displacement <= 100


def test_bearish_fvg_detection() -> None:
    mirrored = [(300 - o, 300 - lo, 300 - h, 300 - c) for (o, h, lo, c) in FVG_ROWS]
    gap = _gap(mirrored)
    assert gap.type is ZoneType.BEARISH_FVG
    assert (gap.bottom, gap.top) == (197, 199)


def test_fvg_minimum_size_filters_tiny_gaps() -> None:
    cfg = replace(SMALL, fvg_min_atr=5.0)
    assert run(ohlc(FVG_ROWS), config=cfg).fvgs.gaps == []


def test_fvg_fill_mitigation_and_invalidation() -> None:
    rows = [*FVG_ROWS, (108.5, 109, 104, 105)]
    assert _gap(rows).filled == 0
    rows.append((105, 106, 102, 104))  # trades to the midpoint
    gap = _gap(rows)
    assert gap.filled == pytest.approx(0.5) and gap.status is ZoneStatus.MITIGATED
    assert gap.mitigated_time is not None
    rows.append((104, 104.5, 100, 100.5))  # CLOSE below the bottom
    gap = _gap(rows)
    assert gap.status is ZoneStatus.INVALIDATED and gap.filled == 1.0
    assert gap.ended_time is not None and gap.status_detail is FeatureStatus.INVALIDATED


def test_wick_through_without_close_is_not_invalidation() -> None:
    rows = [*FVG_ROWS, (108.5, 109, 100.5, 103.5)]  # wick below the bottom, close inside
    gap = _gap(rows)
    assert gap.filled == 1.0 and gap.status is ZoneStatus.MITIGATED


LEGS = [100, 110, 104, 116, 108, 122, 112, 118, 101, 108, 96, 103, 90]


def test_order_blocks_come_from_structure_breaks() -> None:
    analyzer = run(zigzag(LEGS))
    blocks = analyzer.order_blocks.blocks
    assert blocks, "breaks with displacement must create order blocks"
    events = {e.id for e in [*analyzer.swing.events, *analyzer.internal.events]}
    for block in blocks:
        assert block.source_event_id in events
        assert block.top > block.bottom
        assert block.index <= block.end_index < block.created_index
    bullish = [b for b in blocks if b.type is ZoneType.BULLISH_OB]
    first = bullish[0]
    # Last bearish candle(s) before the first bullish break, including the leg low (103.7).
    assert first.bottom == pytest.approx(103.7)


def test_order_blocks_require_displacement() -> None:
    cfg = replace(SMALL, ob_min_displacement=101.0)
    assert run(zigzag(LEGS), config=cfg).order_blocks.blocks == []


def test_bullish_order_blocks_invalidated_by_close_below() -> None:
    analyzer = run(zigzag(LEGS))
    bullish = [b for b in analyzer.order_blocks.blocks if b.type is ZoneType.BULLISH_OB]
    # The sell-off to 90 closes far below every bullish block.
    assert bullish and all(b.status is ZoneStatus.INVALIDATED for b in bullish)
    assert all(b.ended_time is not None and b.quality == 0 for b in bullish)


def test_order_block_mitigation_touch() -> None:
    analyzer = run(zigzag([100, 110, 104, 116, 108, 112]))
    touched = [b for b in analyzer.order_blocks.blocks if b.touches > 0]
    for block in touched:
        assert block.status in (ZoneStatus.MITIGATED, ZoneStatus.INVALIDATED)
        assert block.mitigated_time is not None


def test_order_block_invalidation_needs_tolerance() -> None:
    from app.analysis.models import OrderBlock
    from app.analysis.series import to_bar
    from app.analysis.zones.order_blocks import OrderBlockTracker
    from tests.analysis.helpers import candle

    tracker = OrderBlockTracker(SMALL, 0.1)
    block = OrderBlock(
        "ob", ZoneType.BULLISH_OB, 102, 100, 0, 0, 0, 1, 60, "e", StructureLayer.SWING, 80, 1.0
    )
    tracker.blocks.append(block)
    tracker.on_bar(to_bar(candle(2, 101, 101.5, 99.7, 99.9), 2), atr=2.0)  # 0.1 below: noise
    assert (block.status, block.touches) == (ZoneStatus.MITIGATED, 1)
    tracker.on_bar(to_bar(candle(3, 99.9, 100, 99, 99.5), 3), atr=2.0)  # 0.5 below > 0.2 tol
    assert block.status.value == "invalidated"


def test_premium_discount_positions() -> None:
    rng = DealingRange(StructureLayer.SWING, StructureDirection.BULLISH, 120, 10, 100, 0)
    cfg = SMALL
    pd = premium_discount(rng, 115, cfg)
    assert pd.equilibrium == 110 and pd.position == 75 and pd.zone is PremiumDiscountZone.PREMIUM
    assert premium_discount(rng, 104, cfg).zone is PremiumDiscountZone.DISCOUNT
    assert premium_discount(rng, 110.5, cfg).zone is PremiumDiscountZone.EQUILIBRIUM
    assert premium_discount(rng, 125, cfg).zone is PremiumDiscountZone.ABOVE_RANGE
    assert premium_discount(rng, 95, cfg).position == -25


def test_dealing_range_tracks_current_structure() -> None:
    analyzer = run(zigzag([100, 110, 104, 116, 108, 122, 115]))
    rng = dealing_range(analyzer.swing, analyzer.series)
    assert rng is not None and rng.direction is StructureDirection.BULLISH
    assert rng.low == pytest.approx(107.7)  # protected low
    assert rng.high == pytest.approx(122.3)  # highest high since


def test_ote_bounds_bullish_and_bearish() -> None:
    bull = ote_zone(
        DealingRange(StructureLayer.SWING, StructureDirection.BULLISH, 200, 5, 100, 0), 130, SMALL
    )
    assert bull is not None
    assert bull.upper == pytest.approx(200 - 61.8) and bull.lower == pytest.approx(200 - 79)
    assert bull.focus == pytest.approx(200 - 70.5)
    assert bull.price_in_zone and bull.active and bull.impulse_start == 100
    bear = ote_zone(
        DealingRange(StructureLayer.SWING, StructureDirection.BEARISH, 200, 0, 100, 5), 150, SMALL
    )
    assert bear is not None
    assert bear.lower == pytest.approx(161.8) and bear.upper == pytest.approx(179)
    assert not bear.price_in_zone
    neutral = DealingRange(StructureLayer.SWING, StructureDirection.NEUTRAL, 200, 0, 100, 5)
    assert ote_zone(neutral, 150, SMALL) is None
