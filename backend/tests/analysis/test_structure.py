"""Pivots, HH/HL/LH/LL, BOS, CHoCH, protected levels, displacement."""

from __future__ import annotations

from app.analysis.config import AnalysisConfig
from app.analysis.enums import (
    FeatureStatus,
    PivotSide,
    PivotType,
    StructureDirection,
    StructureEventType,
    StructureLayer,
)
from app.analysis.series import BarSeries, to_bar
from app.analysis.structure.displacement import displacement_score
from app.analysis.structure.pivots import PivotDetector
from tests.analysis.helpers import candle, run, zigzag

LEGS = [100, 110, 104, 116, 108, 122, 112, 118, 101, 108, 96, 103, 90]


def _series(highs: list[float], lows: list[float] | None = None) -> BarSeries:
    lows = lows or [h - 5 for h in highs]
    series = BarSeries(1000)
    for i, (h, lo) in enumerate(zip(highs, lows, strict=True)):
        series.append(to_bar(candle(i, lo + 1, h, lo, lo + 2), i))
    return series


def test_pivot_confirms_only_after_right_bars() -> None:
    highs = [10, 11, 15, 12, 11, 13]
    detector = PivotDetector(StructureLayer.SWING, 2, 2)
    series = BarSeries(1000)
    found_at: dict[int, list[float]] = {}
    for i, h in enumerate(highs):
        series.append(to_bar(candle(i, h - 2, h, h - 5, h - 1), i))
        found_at[i] = [p.price for p in detector.update(series, i) if p.side is PivotSide.HIGH]
    assert found_at[2] == [] and found_at[3] == []  # not yet: needs 2 candles to the right
    assert found_at[4] == [15.0]
    pivot = detector.last_high
    assert pivot == 15.0


def test_pivot_metadata_and_classification() -> None:
    detector = PivotDetector(StructureLayer.SWING, 2, 2)
    series = _series([10, 11, 15, 12, 11, 13, 14, 12, 11, 10])
    pivots = []
    for i in range(len(series)):
        pivots += [p for p in detector.update(series, i) if p.side is PivotSide.HIGH]
    first, second = pivots
    assert (first.price, first.index, first.confirmed_index) == (15.0, 2, 4)
    assert first.type is PivotType.HIGH  # first pivot of the side
    assert first.confirmed_time == series.bar(4).close_time
    assert first.status is FeatureStatus.CONFIRMED and first.layer is StructureLayer.SWING
    assert (second.price, second.type) == (14.0, PivotType.LH)


def test_equal_highs_first_one_is_the_pivot() -> None:
    detector = PivotDetector(StructureLayer.INTERNAL, 2, 2)
    series = _series([10, 11, 15, 15, 12, 11, 10])
    pivots = []
    for i in range(len(series)):
        pivots += [p for p in detector.update(series, i) if p.side is PivotSide.HIGH]
    assert [(p.index, p.price) for p in pivots] == [(2, 15.0)]


def test_developing_pivot_is_marked_and_may_disappear() -> None:
    detector = PivotDetector(StructureLayer.SWING, 2, 2)
    series = _series([10, 11, 15, 12])
    for i in range(len(series)):
        detector.update(series, i)
    dev = [p for p in detector.developing(series, None) if p.side is PivotSide.HIGH]
    assert len(dev) == 1 and dev[0].index == 2 and dev[0].status is FeatureStatus.DEVELOPING
    # A forming candle above 15 cancels that candidate (the developing pivot moves).
    forming = to_bar(candle(4, 14, 16, 11, 15), 4)
    moved = [p for p in detector.developing(series, forming) if p.side is PivotSide.HIGH]
    assert all(p.index != 2 for p in moved)


def test_hh_hl_lh_ll_sequence() -> None:
    analyzer = run(zigzag(LEGS))
    types = [p.type for p in analyzer.swing.pivots]
    assert types[:7] == [
        PivotType.HIGH,
        PivotType.LOW,
        PivotType.HH,
        PivotType.HL,
        PivotType.HH,
        PivotType.HL,
        PivotType.LH,
    ]
    assert PivotType.LL in types
    times = [p.confirmed_time for p in analyzer.swing.pivots]
    assert times == sorted(times)


def test_bos_and_choch_sequence_swing() -> None:
    analyzer = run(zigzag(LEGS))
    events = [(e.type, e.direction, e.level) for e in analyzer.swing.events]
    bull, bear = StructureDirection.BULLISH, StructureDirection.BEARISH
    assert events == [
        (StructureEventType.BOS, bull, 110.3),
        (StructureEventType.BOS, bull, 116.3),
        (StructureEventType.CHOCH, bear, 107.7),  # the protected low, not the 111.7 higher low
        (StructureEventType.BOS, bear, 100.7),
        (StructureEventType.BOS, bear, 95.7),
    ]
    choch = analyzer.swing.events[2]
    assert choch.close < choch.level  # confirmed by a CLOSE beyond the level
    assert choch.confirmed_time > choch.time
    assert 0 <= choch.displacement <= 100
    assert len({e.id for e in analyzer.swing.events}) == len(analyzer.swing.events)


def test_internal_choch_is_earlier_and_labeled_internal() -> None:
    analyzer = run(zigzag(LEGS))
    swing_choch = next(e for e in analyzer.swing.events if e.type is StructureEventType.CHOCH)
    internal_choch = next(e for e in analyzer.internal.events if e.type is StructureEventType.CHOCH)
    assert internal_choch.layer is StructureLayer.INTERNAL
    assert internal_choch.level == 111.7  # trailing protected low = latest internal HL
    assert internal_choch.index < swing_choch.index


def test_protected_levels_lifecycle() -> None:
    analyzer = run(zigzag(LEGS))
    history = analyzer.swing.protected_history
    lows = [p for p in history if p.side is PivotSide.LOW]
    assert [p.price for p in lows] == [103.7, 107.7]
    assert lows[0].status == "superseded" and lows[1].status == "broken"
    assert lows[1].ended_time is not None
    # After the bearish CHoCH the protected high is the top of the last up-leg.
    highs = [p for p in history if p.side is PivotSide.HIGH]
    assert highs[0].price == 122.3
    assert analyzer.swing.protected_high is not None and analyzer.swing.protected_high.active
    assert analyzer.swing.protected_low is None


def test_wick_through_level_is_not_a_bos() -> None:
    rows = zigzag([100, 110, 104])  # pivot high 110.3 confirmed, then pull back
    n = len(rows)
    # Wick to 112 but close back below 110.3: no BOS.
    rows.append(candle(n, 105, 112, 104.5, 109))
    analyzer = run(rows)
    assert analyzer.swing.events == []
    rows.append(candle(n + 1, 109, 111.5, 108.5, 111))  # close above: BOS
    analyzer = run(rows)
    assert [e.type for e in analyzer.swing.events] == [StructureEventType.BOS]


def test_displacement_score_components() -> None:
    cfg = AnalysisConfig()
    strong = to_bar(candle(0, 100, 110.2, 99.8, 110, v=30), 0)
    weak = to_bar(candle(1, 100, 101, 99, 100.1, v=5), 1)
    s = displacement_score(strong, 4.0, 3.0, 4.0, True, cfg)
    w = displacement_score(weak, 4.0, 0.5, 0.1, True, cfg)
    assert s > 90 and w < 15
    against = displacement_score(strong, 4.0, 3.0, 4.0, False, cfg)  # body against direction
    assert against < s


def test_structure_developing_break_does_not_mutate() -> None:
    analyzer = run(zigzag([100, 110, 104]))
    before = list(analyzer.swing.events)
    breaks = analyzer.swing.developing(115.0)
    assert breaks and breaks[0].status is FeatureStatus.DEVELOPING
    assert analyzer.swing.events == before
