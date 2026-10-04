"""BingX payloads taken from the official API documentation examples (+ edge cases)."""

from __future__ import annotations

from typing import Any

CONTRACTS: list[dict[str, Any]] = [
    {
        "contractId": "100",
        "symbol": "BTC-USDT",
        "size": "0.0001",
        "quantityPrecision": 4,
        "pricePrecision": 1,
        "feeRate": 0.0005,
        "tradeMinLimit": 1,
        "maxLongLeverage": 150,
        "maxShortLeverage": 150,
        "currency": "USDT",
        "asset": "BTC",
        "status": 1,
    },
    {
        "contractId": "101",
        "symbol": "ETH-USDT",
        "size": "0.01",
        "quantityPrecision": 2,
        "pricePrecision": 2,
        "feeRate": 0.0005,
        "tradeMinLimit": 1,
        "maxLongLeverage": 125,
        "maxShortLeverage": 125,
        "currency": "USDT",
        "asset": "ETH",
        "status": 1,
        # newer-revision fields
        "tradeMinQuantity": 0.01,
        "tradeMinUSDT": 2,
        "apiStateOpen": "true",
    },
    {  # offline contract
        "symbol": "OLD-USDT",
        "quantityPrecision": 0,
        "pricePrecision": 4,
        "currency": "USDT",
        "asset": "OLD",
        "status": 0,
    },
    {  # not USDT-settled -> filtered
        "symbol": "BTC-USD",
        "quantityPrecision": 4,
        "pricePrecision": 1,
        "currency": "USD",
        "asset": "BTC",
        "status": 1,
    },
    {"symbol": "BAD-USDT", "pricePrecision": "x", "quantityPrecision": 1, "status": 1},
]

KLINES_DOC: list[dict[str, Any]] = [
    {
        "open": "19396.8",
        "close": "19394.4",
        "high": "19397.5",
        "low": "19385.7",
        "volume": "110.05",
        "time": 1666583700000,
    },
    {
        "open": "19394.4",
        "close": "19379.0",
        "high": "19394.4",
        "low": "19368.3",
        "volume": "167.44",
        "time": 1666584000000,
    },
]

TICKERS: list[dict[str, Any]] = [
    {
        "symbol": "BTC-USDT",
        "priceChange": "52.5",
        "priceChangePercent": "0.31",
        "lastPrice": "16880.5",
        "lastQty": "2.2238",
        "highPrice": "16897.5",
        "lowPrice": "16726.0",
        "volume": "245870.1692",
        "quoteVolume": "4151395117.73",
        "openPrice": "16832.0",
        "openTime": 1672026667803,
        "closeTime": 1672026648425,
    },
    {
        "symbol": "VET-USDT",
        "priceChange": "-0.00010",
        "priceChangePercent": "-0.62",
        "lastPrice": "0.01612",
        "lastQty": "193",
        "highPrice": "0.01627",
        "lowPrice": "0.01593",
        "volume": "21566781",
        "quoteVolume": "347658.67",
        "openPrice": "0.01622",
        "openTime": 1672026697663,
        "closeTime": 1672026488862,
    },
]

PREMIUM_INDEX: list[dict[str, Any]] = [
    {
        "symbol": "BTC-USDT",
        "markPrice": "16884.5",
        "indexPrice": "16886.9",
        "lastFundingRate": "0.0001",
        "nextFundingTime": 1672041600000,
    },
]

OPEN_INTEREST: dict[str, Any] = {
    "openInterest": "3289641547.10",
    "symbol": "BTC-USDT",
    "time": 1672026617364,
}

DEPTH: dict[str, Any] = {
    "T": 1672025377603,
    "bids": [["16880.50000000", "1083739.0"], ["16880.00000000", "851709.0"]],
    "asks": [["16881.00000000", "1518457.0"], ["16881.50000000", "1.0"]],
}


def envelope(data: Any, code: int = 0, msg: str = "") -> dict[str, Any]:
    return {"code": code, "msg": msg, "data": data}
