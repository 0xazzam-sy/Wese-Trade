from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.market_data.exceptions import InvalidProviderResponse
from app.market_data.models import SymbolStatus
from app.market_data.okx.parser import (
    is_target_instrument,
    parse_book,
    parse_candle_push,
    parse_candle_row,
    parse_candles,
    parse_funding,
    parse_instruments,
    parse_mark_prices,
    parse_open_interest,
    parse_quote_push,
    parse_tickers,
    to_inst_id,
    to_symbol,
)
from app.market_data.timeframes import Timeframe
from tests.market import fixtures as fx

NOW = datetime(2026, 10, 4, 6, 30, tzinfo=UTC)


def test_symbol_mapping_round_trip() -> None:
    assert to_symbol("BTC-USDT-SWAP") == "BTCUSDT"
    assert to_symbol("1000PEPE-USDT-SWAP") == "1000PEPEUSDT"
    assert to_inst_id("BTCUSDT") == "BTC-USDT-SWAP"
    assert to_inst_id(to_symbol("SOL-USDT-SWAP")) == "SOL-USDT-SWAP"
    assert is_target_instrument("eth-usdt-swap")
    assert not is_target_instrument("BTC-USD-SWAP")
    assert not is_target_instrument("BTC-USDT")


def test_instruments_filter_and_exact_filters() -> None:
    symbols = {s.symbol: s for s in parse_instruments(fx.INSTRUMENTS)}
    assert set(symbols) == {"BTCUSDT", "ETHUSDT", "OLDUSDT"}  # inverse excluded, malformed skipped
    btc = symbols["BTCUSDT"]
    assert btc.exchange_symbol == "BTC-USDT-SWAP"
    assert btc.base_asset == "BTC"
    assert btc.quote_asset == "USDT"
    assert btc.display_name == "BTC/USDT"
    assert btc.contract_type == "perpetual"
    assert btc.tick_size == Decimal("0.1")  # tickSz, not derived from a precision
    assert btc.step_size == Decimal("0.01")  # lotSz
    assert btc.min_quantity == Decimal("0.01")  # minSz (contracts)
    assert btc.price_precision == 1
    assert btc.quantity_precision == 2
    assert btc.contract_value == Decimal("0.01")
    assert btc.contract_value_currency == "BTC"
    assert btc.max_leverage == 100
    assert btc.min_notional is None
    assert btc.status is SymbolStatus.ACTIVE
    assert btc.trading_enabled
    old = symbols["OLDUSDT"]
    assert old.status is SymbolStatus.UNAVAILABLE
    assert not old.trading_enabled
    assert old.tick_size == Decimal("0.0001")
    assert old.price_precision == 4


def test_instruments_requires_list() -> None:
    with pytest.raises(InvalidProviderResponse):
        parse_instruments({"instId": "BTC-USDT-SWAP"})


def test_candle_rows_confirm_flag_sorting_and_volume() -> None:
    candles = parse_candles(fx.CANDLES_1H, "BTCUSDT", Timeframe.H1)
    assert [c.open_ms for c in candles] == [1791090000000, 1791093600000]  # oldest first
    closed, forming = candles
    assert closed.is_closed is True  # confirm = "1"
    assert forming.is_closed is False  # confirm = "0"
    assert closed.open == Decimal("84778.7")
    assert closed.high == Decimal("84883.2")
    assert closed.low == Decimal("84778.7")
    assert closed.close == Decimal("84870")
    assert closed.volume == Decimal("482.4073")  # base currency (volCcy), not contracts
    assert closed.quote_volume == Decimal("40929985.76105")
    assert closed.open_time == datetime(2026, 10, 4, 5, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    "row",
    [
        ["1791090000000", "1", "0.5", "1", "1", "1", "1", "1", "1"],  # high < open
        ["1791090000000", "1", "2", "1", "1", "1", "-1", "1", "1"],  # negative volume
        ["1791090000000", "1", "2", "1", "1", "1", "1", "1", "x"],  # bad confirm
        ["1791090000001", "1", "2", "1", "1", "1", "1", "1", "1"],  # not bar-aligned
        ["1791090000000", "NaN", "2", "1", "1", "1", "1", "1", "1"],
        ["1791090000000", "1", "2"],  # too short
    ],
)
def test_malformed_candle_rows_rejected(row: list[str]) -> None:
    with pytest.raises(InvalidProviderResponse):
        parse_candle_row(row, "BTCUSDT", Timeframe.H1)


def test_duplicate_rows_closed_wins_and_bad_rows_skipped() -> None:
    forming = ["1791090000000", "1", "2", "1", "1.5", "1", "1", "1", "0"]
    closed = ["1791090000000", "1", "2", "1", "1.7", "1", "1", "1", "1"]
    bad = ["1791093600000", "1", "0.1", "1", "1", "1", "1", "1", "1"]
    candles = parse_candles([closed, forming, bad], "BTCUSDT", Timeframe.H1)
    assert len(candles) == 1
    assert candles[0].is_closed
    assert candles[0].close == Decimal("1.7")


def test_tickers_book_mark_funding_open_interest() -> None:
    tickers = {t.symbol: t for t in parse_tickers(fx.TICKERS)}
    assert set(tickers) == {"BTCUSDT", "ETHUSDT"}
    btc = tickers["BTCUSDT"]
    assert btc.last_price == Decimal("84972.5")
    assert btc.open_price == Decimal("84611.6")
    assert btc.price_change == Decimal("360.9")
    assert btc.price_change_percent.quantize(Decimal("0.0001")) == Decimal("0.4265")
    assert btc.high_24h == Decimal("85044.6")
    assert btc.low_24h == Decimal("84504")
    assert btc.volume_24h == Decimal("18775.1171")  # base currency
    assert btc.quote_volume_24h is None  # not estimated
    assert btc.bid == Decimal("84972.4")
    assert btc.ask == Decimal("84972.5")

    book = parse_book(fx.TICKER_BTC)
    assert book is not None
    assert book.spread == Decimal("0.1")
    assert book.bid_qty == Decimal("310.68")
    assert parse_book({**fx.TICKER_BTC, "bidPx": "", "askPx": ""}) is None

    marks = parse_mark_prices(fx.MARK_PRICES)
    assert marks["BTCUSDT"][0] == Decimal("84972.3")

    (funding,) = parse_funding(fx.FUNDING, now=NOW)  # inverse filtered
    assert funding.symbol == "BTCUSDT"
    assert funding.funding_rate == Decimal("0.0000289853709374")
    assert funding.next_funding_time == datetime(2026, 10, 4, 8, 0, tzinfo=UTC)  # fundingTime

    oi = parse_open_interest(fx.OPEN_INTEREST, "BTCUSDT")
    assert oi.contracts == Decimal("2851122.41000000954")
    assert oi.base == Decimal("28511.2241000000954")
    assert oi.usd == Decimal("2422669989.8372581063765")
    with pytest.raises(InvalidProviderResponse):
        parse_open_interest([], "BTCUSDT")


def test_ws_candle_and_quote_pushes() -> None:
    push = {
        "arg": {"channel": "candle1m", "instId": "BTC-USDT-SWAP"},
        "data": [
            [
                "1791095160000",
                "84888.0",
                "84888.0",
                "84882.9",
                "84882.9",
                "233.98",
                "2.3398",
                "198613.27",
                "0",
            ]
        ],
    }
    (candle,) = parse_candle_push(push)
    assert candle.symbol == "BTCUSDT"
    assert candle.timeframe is Timeframe.M1
    assert candle.is_closed is False
    assert candle.close == Decimal("84882.9")
    assert (
        parse_candle_push(
            {"arg": {"channel": "candle7m", "instId": "BTC-USDT-SWAP"}, "data": push["data"]}
        )
        == []
    )
    assert (
        parse_candle_push(
            {"arg": {"channel": "candle1H", "instId": "BTC-USDT-SWAP"}, "data": [["bad"]]}
        )
        == []
    )

    ticker = {"arg": {"channel": "tickers", "instId": "BTC-USDT-SWAP"}, "data": [fx.TICKER_BTC]}
    (quote,) = parse_quote_push(ticker)
    assert quote.last == Decimal("84972.5")
    assert quote.bid == Decimal("84972.4")
    assert quote.ask == Decimal("84972.5")
    assert quote.mark is None
    mark = {
        "arg": {"channel": "mark-price", "instId": "ETH-USDT-SWAP"},
        "data": [
            {
                "instId": "ETH-USDT-SWAP",
                "instType": "SWAP",
                "markPx": "2690.87",
                "ts": "1791095179110",
            }
        ],
    }
    (mq,) = parse_quote_push(mark)
    assert mq.symbol == "ETHUSDT"
    assert mq.mark == Decimal("2690.87")
    assert mq.last is None
