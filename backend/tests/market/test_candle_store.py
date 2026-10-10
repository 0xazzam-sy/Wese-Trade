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


def test_trusted_close_finalizes_immediately_and_inferred_close_can_be_corrected() -> None:
    s = stream()
    s.apply_live(candle(0, c="101", closed=False), trust_close=True)
    closed = s.apply_live(candle(0, c="102", closed=True), trust_close=True)
    assert [(c.open_ms, c.is_closed) for c in closed.events] == [(at(0), True)]
    assert s.forming is None
    # Confirmed by the exchange: a later replay with other values never changes it.
    assert s.apply_live(candle(0, c="1", closed=True), trust_close=True).events == []
    assert s.closed[at(0)].close == Decimal("102")

    # Next candle's close arrives late: we infer it from the newer candle first ...
    s.apply_live(candle(5, c="103", closed=False), trust_close=True)
    s.apply_live(candle(10, c="104", closed=False), trust_close=True)
    assert at(5) in s.inferred_closed
    # ... and the authoritative close may still correct it, exactly once.
    fixed = s.apply_live(candle(5, c="103.5", closed=True), trust_close=True)
    assert [c.close for c in fixed.events] == [Decimal("103.5")]
    assert at(5) not in s.inferred_closed
    assert s.apply_live(candle(5, c="7", closed=True), trust_close=True).events == []


def test_closed_push_after_missed_candles_is_a_gap() -> None:
    s = stream()
    s.apply_live(candle(0, closed=True), trust_close=True)
    result = s.apply_live(candle(15, closed=True), trust_close=True)
    assert result.gap is True


def test_stream_cache_never_evicts_the_requested_stream() -> None:
    """v1.2 regression: with every cached stream live (scanner), requesting a NEW stream
    above the cap must return it, not evict it and raise KeyError."""
    from typing import Any

    from app.market_data.services import candle_service
    from app.market_data.services.candle_service import MAX_STREAMS, CandleService

    service = CandleService(provider=None)  # type: ignore[arg-type]
    for i in range(MAX_STREAMS):
        service.stream(f"S{i}USDT", Timeframe.M15).live = True
    extra: Any = service.stream("NEWUSDT", Timeframe.M15)
    assert extra.symbol == "NEWUSDT"
    assert service.existing("NEWUSDT", Timeframe.M15) is extra
    assert len(service._streams) == MAX_STREAMS + 1  # live streams are never dropped
    service.stream("NEWUSDT", Timeframe.M15).live = False
    service.stream("OTHERUSDT", Timeframe.M15)  # idle overflow is evicted again
    assert len(service._streams) == MAX_STREAMS + 1
    assert candle_service.MAX_STREAMS >= 128
