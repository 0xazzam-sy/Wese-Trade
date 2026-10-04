from __future__ import annotations

from decimal import Decimal

from app.market_data.services.candle_service import CandleStream
from app.market_data.timeframes import Timeframe
from tests.market.helpers import at, candle


def stream() -> CandleStream:
    return CandleStream("BTCUSDT", Timeframe.M5)


def test_live_updates_finalize_only_when_newer_candle_arrives() -> None:
    s = stream()
    first = s.apply_live(candle(0, c="101", closed=True))  # WS flags are never trusted
    assert first.events[0].is_closed is False
    assert s.apply_live(candle(0, c="101")).events == []  # duplicate
    update = s.apply_live(candle(0, c="103"))
    assert update.events[0].close == Decimal("103")

    rolled = s.apply_live(candle(5, c="104"))
    assert [(c.open_ms, c.is_closed) for c in rolled.events] == [(at(0), True), (at(5), False)]
    assert rolled.gap is False
    assert s.apply_live(candle(0, c="1")).events == []  # out-of-order late push ignored


def test_gap_detection() -> None:
    s = stream()
    s.apply_live(candle(0))
    result = s.apply_live(candle(15))
    assert result.gap is True


def test_rest_merge_reconciles_closed_and_forming() -> None:
    s = stream()
    s.apply_live(candle(0, c="101"))
    changed = s.merge_rest([candle(0, c="102"), candle(5, c="103", closed=False)])
    assert [c.open_ms for c in changed] == [at(0), at(5)]
    assert s.closed[at(0)].close == Decimal("102")
    assert s.forming is not None
    assert s.forming.open_ms == at(5)
    assert s.merge_rest([candle(0, c="102")]) == []  # dedupe by open time
    history = s.history(10)
    assert [c.open_ms for c in history] == [at(0), at(5)]
    assert history[-1].is_closed is False


def test_coverage_requires_contiguous_closed_and_current_forming() -> None:
    s = stream()
    s.merge_rest([candle(m) for m in (0, 5, 10)] + [candle(15, closed=False)])
    assert s.has_coverage(4, at(16)) is True
    assert s.has_coverage(5, at(16)) is False  # 11:55 missing
    del s.closed[at(5)]
    assert s.has_coverage(4, at(16)) is False
