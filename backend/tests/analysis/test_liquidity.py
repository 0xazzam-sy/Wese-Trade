"""Equal highs/lows, liquidity pools, sweeps vs breakouts."""

from __future__ import annotations

from app.analysis.engine import MarketAnalyzer
from app.analysis.enums import (
    LiquiditySide,
    LiquiditySource,
    PoolStatus,
    StructureDirection,
    StructureEventType,
    StructureLayer,
)
from app.analysis.liquidity.pools import LiquidityTracker
from app.analysis.models import LiquidityPool, StructureEvent
from app.analysis.series import to_bar
from tests.analysis.helpers import SMALL, candle, ohlc, run

EQH_ROWS = [
    (100, 101, 99, 100),
    (100, 102, 99.5, 101.5),
    (101.5, 110, 101, 105),  # first high 110
    (105, 106, 103, 104),
    (104, 105, 102, 103),
    (103, 108, 102.5, 107),
    (107, 110.05, 106, 108),  # second high 110.05 (within tolerance)
    (108, 109, 105, 106),
    (106, 107, 104, 105),
]


def _eqh() -> list:  # type: ignore[type-arg]
    return [
        p for p in run(ohlc(EQH_ROWS)).liquidity.pools if p.source is LiquiditySource.EQUAL_HIGHS
    ]


def test_equal_highs_detected_with_tolerance() -> None:
    analyzer = run(ohlc(EQH_ROWS))
    levels = analyzer.liquidity.equal_levels
    assert len(levels) == 1
    eqh = levels[0]
    assert eqh.side is LiquiditySide.BUY_SIDE
    assert eqh.level == 110.05  # the most extreme touch
    assert eqh.touches == 2
    assert eqh.first_index == 2 and eqh.last_index == 6
    assert eqh.tolerance >= 2 * 0.01  # tick floor
    assert 0 < eqh.strength <= 100 and eqh.active
    pools = _eqh()
    assert len(pools) == 1 and pools[0].status is PoolStatus.ACTIVE


def test_highs_too_far_apart_are_not_equal() -> None:
    rows = list(EQH_ROWS)
    rows[6] = (107, 112, 106, 108)  # 2 points above: far beyond 0.1 ATR
    assert run(ohlc(rows)).liquidity.equal_levels == []


def test_equal_lows_mirror() -> None:
    mirrored = [(300 - o, 300 - lo, 300 - h, 300 - c) for (o, h, lo, c) in EQH_ROWS]
    analyzer = run(ohlc(mirrored))
    lows = [e for e in analyzer.liquidity.equal_levels if e.side is LiquiditySide.SELL_SIDE]
    assert len(lows) == 1 and lows[0].level == 300 - 110.05


def test_sweep_wick_beyond_close_back_inside() -> None:
    rows = [*EQH_ROWS, (105, 110.6, 104, 109)]
    analyzer = run(ohlc(rows))
    sweeps = analyzer.liquidity.sweeps
    assert len(sweeps) == 1
    sweep = sweeps[0]
    assert sweep.side is LiquiditySide.BUY_SIDE and sweep.level == 110.05
    assert sweep.extreme == 110.6 and sweep.close == 109
    assert abs(sweep.penetration - 0.55) < 1e-9
    assert analyzer.liquidity.counts["sweeps"] == 1  # the equal touch at 110.05 was no sweep
    assert 0 < sweep.rejection <= 1 and 0 <= sweep.quality <= 100
    pool = next(p for p in analyzer.liquidity.pools if p.id == sweep.pool_id)
    assert pool.status is PoolStatus.SWEPT and pool.ended_time == sweep.confirmed_time
    assert analyzer.liquidity.equal_levels[0].status is PoolStatus.SWEPT


def test_close_beyond_is_breakout_not_sweep() -> None:
    rows = [*EQH_ROWS, (105, 111, 104, 110.8)]
    analyzer = run(ohlc(rows))
    assert analyzer.liquidity.sweeps == []
    pool = _pool(analyzer, LiquiditySource.EQUAL_HIGHS)
    assert pool.status is PoolStatus.BROKEN
    assert analyzer.liquidity.counts["breakouts"] >= 1


def _pool(analyzer: MarketAnalyzer, source: LiquiditySource) -> LiquidityPool:
    return next(p for p in analyzer.liquidity.pools if p.source is source)


def test_developing_sweep_from_forming_candle() -> None:
    analyzer = run(ohlc(EQH_ROWS))
    forming = to_bar(candle(len(EQH_ROWS), 105, 110.6, 104, 108, closed=False), len(EQH_ROWS))
    dev = analyzer.liquidity.developing(forming)
    assert len(dev) == 1 and dev[0].level == 110.05
    assert analyzer.liquidity.sweeps == []  # nothing confirmed


def test_sweep_structure_response_annotation() -> None:
    tracker = LiquidityTracker(SMALL, 0.01)
    pool = LiquidityPool("p1", LiquiditySide.BUY_SIDE, LiquiditySource.SWING_HIGH, 110, 0, 0, 60)
    tracker.pools.append(pool)
    bar = to_bar(candle(5, 105, 111, 104, 108), 5)
    sweeps = tracker.on_bar(bar, 2.0, 1.0)
    assert len(sweeps) == 1
    event = StructureEvent(
        id="internal:CHOCH:bearish:1",
        layer=StructureLayer.INTERNAL,
        type=StructureEventType.CHOCH,
        direction=StructureDirection.BEARISH,
        level=105,
        level_index=3,
        level_time=0,
        index=8,
        time=480,
        confirmed_time=540,
        close=104,
        displacement=50,
        relative_volume=1.0,
        volume_confirmed=False,
    )
    tracker.note_structure([event])
    assert sweeps[0].structure_response == event.id and sweeps[0].response_time == 540


def test_poke_within_tolerance_is_not_a_sweep() -> None:
    rows = [*EQH_ROWS, (105, 110.06, 104, 109)]  # 0.01 beyond: inside the tolerance band
    analyzer = run(ohlc(rows))
    assert analyzer.liquidity.sweeps == []
    assert _pool(analyzer, LiquiditySource.EQUAL_HIGHS).status is PoolStatus.ACTIVE


def test_swing_pivots_become_pools_and_expire() -> None:
    from dataclasses import replace

    from tests.analysis.helpers import zigzag

    cfg = replace(SMALL, pool_max_age=12)
    analyzer = run(zigzag([100, 110, 104, 106, 103, 105, 104, 105, 104, 105]), config=cfg)
    sources = {p.source for p in analyzer.liquidity.pools}
    assert LiquiditySource.SWING_HIGH in sources or LiquiditySource.EQUAL_HIGHS in sources
    statuses = {p.status for p in analyzer.liquidity.pools}
    assert PoolStatus.EXPIRED in statuses or PoolStatus.SWEPT in statuses
