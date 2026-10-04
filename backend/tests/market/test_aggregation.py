from __future__ import annotations

from decimal import Decimal

import pytest

from app.market_data.services.aggregation import LiveAggregator, aggregate_history, build_bucket
from app.market_data.timeframes import Timeframe
from tests.market.helpers import BASE_MS, at, candle


def test_bucket_alignment_is_utc_wall_clock() -> None:
    tf = Timeframe.M10
    assert tf.bucket_start_ms(at(0)) == at(0)
    assert tf.bucket_start_ms(at(9.999)) == at(0)
    assert tf.bucket_start_ms(at(10)) == at(10)  # exact boundary starts the next bucket
    assert tf.bucket_start_ms(at(5)) == at(0)  # 12:05 5m child belongs to 12:00 bucket
    assert tf.bucket_start_ms(at(15)) == at(10)
    assert BASE_MS % (600 * 1000) == 0


def test_build_bucket_ohlcv() -> None:
    first = candle(0, o="100", h="120", low="95", c="110", v="2", qv="200")
    second = candle(5, o="110", h="130", low="90", c="125", v="3", qv="300")
    result = build_bucket([second, first], now_ms=at(10))
    assert result.timeframe is Timeframe.M10
    assert result.open_ms == at(0)
    assert result.open == Decimal("100")
    assert result.high == Decimal("130")
    assert result.low == Decimal("90")
    assert result.close == Decimal("125")
    assert result.volume == Decimal("5")
    assert result.quote_volume == Decimal("500")
    assert result.is_closed is True


def test_bucket_not_closed_before_end_or_with_open_child() -> None:
    first, second = candle(0), candle(5)
    assert build_bucket([first, second], now_ms=at(9.99)).is_closed is False
    assert build_bucket([first, candle(5, closed=False)], now_ms=at(11)).is_closed is False
    assert build_bucket([first], now_ms=at(11)).is_closed is False  # missing child


def test_children_from_different_buckets_rejected() -> None:
    with pytest.raises(ValueError, match="different"):
        build_bucket([candle(5), candle(10)], now_ms=at(30))


def test_history_does_not_pair_by_array_position() -> None:
    # Starts at 12:05 (second half of a bucket): naive pairing would merge 12:05+12:10.
    source = [candle(m) for m in (5, 10, 15, 20, 25)]
    result = aggregate_history(source, now_ms=at(40))
    assert [c.open_ms for c in result] == [at(10), at(20)]  # 12:00 bucket incomplete -> dropped
    assert all(c.is_closed for c in result)


def test_history_missing_child_is_not_fabricated_and_current_bucket_is_forming() -> None:
    source = [candle(0), candle(5), candle(10), candle(20), candle(25), candle(30, closed=False)]
    result = aggregate_history(source, now_ms=at(32))
    opens = [c.open_ms for c in result]
    assert opens == [at(0), at(20), at(30)]  # 12:10 bucket missing 12:15 -> excluded
    assert result[-1].is_closed is False
    assert result[-1].open_ms == at(30)


def test_history_rejects_wrong_source_timeframe() -> None:
    with pytest.raises(ValueError, match="5m"):
        aggregate_history([candle(0, tf=Timeframe.M1)], now_ms=at(10))


def test_live_aggregation_updates_duplicates_and_rollover() -> None:
    agg = LiveAggregator("BTCUSDT")
    agg.seed([candle(0, c="101")], now_ms=at(6))  # first child known from history

    first = agg.update(candle(5, c="102", closed=False), now_ms=at(6))
    assert len(first) == 1
    assert first[0].open_ms == at(0)
    assert first[0].close == Decimal("102")
    assert first[0].is_closed is False

    assert agg.update(candle(5, c="102", closed=False), now_ms=at(7)) == []  # duplicate

    update = agg.update(candle(5, c="104", h="140", closed=False), now_ms=at(8))
    assert update[0].high == Decimal("140")
    assert update[0].is_closed is False

    # Rollover: the 12:10 child arrives -> 12:00 bucket finalized exactly once, then forming.
    rolled = agg.update(candle(10, c="106", closed=False), now_ms=at(10.1))
    assert [c.open_ms for c in rolled] == [at(0), at(10)]
    assert rolled[0].is_closed is True
    assert rolled[0].close == Decimal("104")
    assert rolled[1].is_closed is False

    # Later pushes for the finished bucket are ignored.
    assert agg.update(candle(5, c="999"), now_ms=at(11)) == []


def test_live_closed_child_pair_emits_close_once() -> None:
    agg = LiveAggregator("BTCUSDT")
    agg.seed([candle(0)], now_ms=at(9))
    out = agg.update(candle(5, closed=True), now_ms=at(10.05))
    assert len(out) == 1
    assert out[0].is_closed
    assert agg.update(candle(5, closed=True, c="106"), now_ms=at(10.1)) == []


def test_live_rollover_with_missing_child_emits_no_closed_candle() -> None:
    agg = LiveAggregator("BTCUSDT")
    agg.seed([], now_ms=at(7))
    agg.update(candle(5, closed=False), now_ms=at(7))  # 12:00 child never seen
    rolled = agg.update(candle(10, closed=False), now_ms=at(10.1))
    assert [c.open_ms for c in rolled] == [at(10)]
    assert rolled[0].is_closed is False
