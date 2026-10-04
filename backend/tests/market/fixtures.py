"""OKX payloads captured from the real public API on 2026-10-04 (trimmed), plus edge cases."""

from __future__ import annotations

from typing import Any


def _inst(
    inst_id: str, tick: str, lot: str, ct_val: str, state: str = "live", **extra: Any
) -> dict[str, Any]:
    base = inst_id.split("-")[0]
    return {
        "instId": inst_id,
        "instType": "SWAP",
        "instFamily": f"{base}-USDT",
        "uly": f"{base}-USDT",
        "baseCcy": "",
        "quoteCcy": "",
        "settleCcy": "USDT",
        "ctType": "linear",
        "ctVal": ct_val,
        "ctValCcy": base,
        "ctMult": "1",
        "tickSz": tick,
        "lotSz": lot,
        "minSz": lot,
        "lever": "100",
        "maxLmtSz": "100000000",
        "maxMktSz": "35000",
        "state": state,
        "listTime": "1573557408000",
        **extra,
    }


INSTRUMENTS: list[dict[str, Any]] = [
    _inst("BTC-USDT-SWAP", "0.1", "0.01", "0.01"),
    _inst("ETH-USDT-SWAP", "0.01", "0.01", "0.1"),
    _inst("OLD-USDT-SWAP", "0.0001", "1", "10", state="suspend"),
    # inverse (coin-margined) swap: excluded
    {
        **_inst("BTC-USD-SWAP", "0.1", "1", "100"),
        "settleCcy": "BTC",
        "ctType": "inverse",
        "ctValCcy": "USD",
    },
    # malformed tick size: skipped
    _inst("BAD-USDT-SWAP", "x", "1", "1"),
]

# [ts, o, h, l, c, vol(contracts), volCcy(base), volCcyQuote, confirm] - newest first, as OKX sends.
CANDLES_1H: list[list[str]] = [
    [
        "1791093600000",
        "84870.1",
        "85044.6",
        "84830.8",
        "84972.5",
        "87528.89",
        "875.2889",
        "74338928.50361",
        "0",
    ],
    [
        "1791090000000",
        "84778.7",
        "84883.2",
        "84778.7",
        "84870",
        "48240.73",
        "482.4073",
        "40929985.76105",
        "1",
    ],
]

TICKER_BTC: dict[str, Any] = {
    "instType": "SWAP",
    "instId": "BTC-USDT-SWAP",
    "last": "84972.5",
    "lastSz": "0.35",
    "askPx": "84972.5",
    "askSz": "1541.55",
    "bidPx": "84972.4",
    "bidSz": "310.68",
    "open24h": "84611.6",
    "high24h": "85044.6",
    "low24h": "84504",
    "volCcy24h": "18775.1171",
    "vol24h": "1877511.71",
    "ts": "1791095588271",
    "sodUtc0": "84719.9",
    "sodUtc8": "84825.4",
}
TICKERS: list[dict[str, Any]] = [
    TICKER_BTC,
    {
        **TICKER_BTC,
        "instId": "ETH-USDT-SWAP",
        "last": "2691.5",
        "open24h": "2700",
        "high24h": "2720",
        "low24h": "2680",
        "volCcy24h": "350000",
        "bidPx": "2691.49",
        "askPx": "2691.5",
    },
    {**TICKER_BTC, "instId": "BTC-USD-SWAP"},  # inverse: ignored
]

FUNDING: list[dict[str, Any]] = [
    {
        "instId": "BTC-USDT-SWAP",
        "instType": "SWAP",
        "fundingRate": "0.0000289853709374",
        "fundingTime": "1791100800000",
        "nextFundingTime": "1791129600000",
        "method": "current_period",
    },
    {
        "instId": "BTC-USD-SWAP",
        "instType": "SWAP",
        "fundingRate": "0.0001",
        "fundingTime": "1791100800000",
    },
]

MARK_PRICES: list[dict[str, Any]] = [
    {"instId": "BTC-USDT-SWAP", "instType": "SWAP", "markPx": "84972.3", "ts": "1791095589650"},
]

OPEN_INTEREST: list[dict[str, Any]] = [
    {
        "instId": "BTC-USDT-SWAP",
        "instType": "SWAP",
        "oi": "2851122.41000000954",
        "oiCcy": "28511.2241000000954",
        "oiUsd": "2422669989.8372581063765",
        "ts": "1791095589239",
    }
]


def envelope(data: Any, code: str = "0", msg: str = "") -> dict[str, Any]:
    return {"code": code, "msg": msg, "data": data}
