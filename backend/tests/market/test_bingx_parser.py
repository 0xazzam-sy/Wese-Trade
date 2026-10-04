from __future__ import annotations

import gzip
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.market_data.bingx.exceptions import BingXInvalidResponse
from app.market_data.bingx.parser import (
    decode_frame,
    normalize_symbol,
    parse_book_from_depth,
    parse_contracts,
    parse_funding,
    parse_kline,
    parse_kline_push,
    parse_klines,
    parse_open_interest,
    parse_tickers,
    split_data_type,
)
from app.market_data.models import SymbolStatus
from app.market_data.timeframes import Timeframe
from tests.market import fixtures as fx

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
NOW_MS = int(NOW.timestamp() * 1000)


def test_normalize_symbol() -> None:
    assert normalize_symbol("BTC-USDT") == "BTCUSDT"
    assert normalize_symbol("1000pepe-USDT") == "1000PEPEUSDT"


def test_contract_parsing_filters_and_normalizes() -> None:
    symbols = {s.symbol: s for s in parse_contracts(fx.CONTRACTS)}
    assert set(symbols) == {"BTCUSDT", "ETHUSDT", "OLDUSDT"}  # BTC-USD filtered, BAD skipped

    btc = symbols["BTCUSDT"]
    assert btc.exchange_symbol == "BTC-USDT"
    assert btc.base_asset == "BTC" and btc.quote_asset == "USDT"
    assert btc.display_name == "BTC/USDT"
    assert btc.price_precision == 1
    assert btc.tick_size == Decimal("0.1")
    assert btc.step_size == Decimal("0.0001")
    assert btc.max_leverage == 150
    assert btc.status is SymbolStatus.ACTIVE and btc.trading_enabled

    eth = symbols["ETHUSDT"]
    assert eth.tick_size == Decimal("0.01")
    assert eth.min_quantity == Decimal("0.01")
    assert eth.min_notional == Decimal("2")

    old = symbols["OLDUSDT"]
    assert old.status is SymbolStatus.UNAVAILABLE and not old.trading_enabled


def test_contracts_requires_list() -> None:
    with pytest.raises(BingXInvalidResponse):
        parse_contracts({"symbol": "BTC-USDT"})


def test_kline_parsing_doc_example() -> None:
    candles = parse_klines(list(reversed(fx.KLINES_DOC)), "BTCUSDT", Timeframe.M5, now_ms=NOW_MS)
    assert [c.open_ms for c in candles] == [1666583700000, 1666584000000]  # sorted
    first = candles[0]
    assert first.open == Decimal("19396.8") and first.close == Decimal("19394.4")
    assert first.high == Decimal("19397.5") and first.low == Decimal("19385.7")
    assert first.volume == Decimal("110.05")
    assert first.open_time == datetime(2022, 10, 24, 3, 55, tzinfo=UTC)
    assert first.close_time == datetime(2022, 10, 24, 4, 0, tzinfo=UTC)
    assert first.is_closed


def test_forming_candle_is_not_closed() -> None:
    raw = dict(fx.KLINES_DOC[0], time=NOW_MS + 60_000)  # 12:01 -> bucket 12:00-12:05 forming
    candle = parse_kline(raw, "BTCUSDT", Timeframe.M5, now_ms=NOW_MS)
    assert candle.is_closed is False
    assert candle.open_ms == NOW_MS


def test_duplicate_klines_last_wins_and_malformed_skipped() -> None:
    dup = dict(fx.KLINES_DOC[0], close="19390.0", low="19385.7")
    bad_ohlc = dict(fx.KLINES_DOC[1], time=1666584300000, high="1")  # high < open
    bad_value = dict(fx.KLINES_DOC[1], time=1666584600000, open="NaN")
    candles = parse_klines(
        [fx.KLINES_DOC[0], dup, bad_ohlc, bad_value], "BTCUSDT", Timeframe.M5, now_ms=NOW_MS
    )
    assert len(candles) == 1
    assert candles[0].close == Decimal("19390.0")


def test_kline_close_time_style_timestamp_floors_to_open() -> None:
    raw = {"o": "1", "h": "2", "l": "1", "c": "2", "v": "3", "T": 1649832779999}
    candle = parse_kline(raw, "BTCUSDT", Timeframe.M1, now_ms=NOW_MS)
    assert candle.open_ms == 1649832720000


def test_ticker_parsing() -> None:
    tickers = {t.symbol: t for t in parse_tickers([*fx.TICKERS, {"symbol": "X-USD"}], now=NOW)}
    assert set(tickers) == {"BTCUSDT", "VETUSDT"}
    btc = tickers["BTCUSDT"]
    assert btc.last_price == Decimal("16880.5")
    assert btc.price_change_percent == Decimal("0.31")
    assert btc.open_price == Decimal("16832.0")
    assert btc.quote_volume_24h == Decimal("4151395117.73")
    assert btc.bid is None and btc.ask is None
    assert tickers["VETUSDT"].price_change == Decimal("-0.00010")


def test_funding_parsing_absolute_and_relative_next_time() -> None:
    absolute = parse_funding(fx.PREMIUM_INDEX, now=NOW)[0]
    assert absolute.funding_rate == Decimal("0.0001")
    assert absolute.mark_price == Decimal("16884.5")
    assert absolute.next_funding_time == datetime(2022, 12, 26, 8, 0, tzinfo=UTC)

    relative = parse_funding([dict(fx.PREMIUM_INDEX[0], nextFundingTime=3_600_000)], now=NOW)[0]
    assert relative.next_funding_time == datetime(2026, 10, 3, 13, 0, tzinfo=UTC)


def test_open_interest_and_book() -> None:
    oi = parse_open_interest(fx.OPEN_INTEREST, "BTCUSDT", now=NOW)
    assert oi.value == Decimal("3289641547.10")
    book = parse_book_from_depth(fx.DEPTH, "BTCUSDT", now=NOW)
    assert book is not None
    assert book.bid == Decimal("16880.5") and book.ask == Decimal("16881")
    assert book.spread == Decimal("0.5")
    assert parse_book_from_depth({"bids": [], "asks": []}, "BTCUSDT", now=NOW) is None


def test_ws_frame_decoding_and_kline_push() -> None:
    assert decode_frame(gzip.compress(b"Ping")) == "Ping"
    assert decode_frame("plain") == "plain"
    assert split_data_type("BTC-USDT@kline_5m") == ("BTC-USDT", Timeframe.M5)
    assert split_data_type("BTC-USDT@kline_10m") is None  # not native
    assert split_data_type("BTC-USDT@trade") is None

    doc_push = {
        "code": 0,
        "data": {
            "T": 1649832779999,
            "c": "54564.31",
            "h": "54711.73",
            "l": "54418.27",
            "o": "54577.41",
            "v": "1607.0727000000002",
        },
        "s": "BTC-USDT",
        "dataType": "BTC-USDT@kline_1m",
    }
    (candle,) = parse_kline_push(doc_push, now_ms=NOW_MS)
    assert candle.symbol == "BTCUSDT" and candle.timeframe is Timeframe.M1
    assert candle.close == Decimal("54564.31")
    assert candle.volume == Decimal("1607.0727000000002")

    list_push = dict(doc_push, data=[doc_push["data"], {"T": "bad"}])
    assert len(parse_kline_push(list_push, now_ms=NOW_MS)) == 1
