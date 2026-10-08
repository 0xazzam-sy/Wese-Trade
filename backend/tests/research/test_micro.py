"""Phase 8 microstructure data integrity: trade-archive reduction and the live collector."""

from __future__ import annotations

import gzip
import io
import json
import math
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from app.research.ltf5.data import HoldoutLockedError
from app.research.micro import collector as col
from app.research.micro import trades as tr


def _csv(rows: list[tuple[int, str, float, float, int]]) -> io.StringIO:
    head = "instrument_name,trade_id,side,price,size,created_time,source"
    body = [f"ETH-USDT-SWAP,{i},{s},{p},{z},{t},0" for i, s, p, z, t in rows]
    return io.StringIO("\n".join([head, *body]) + "\n")


def test_reduce_day_buckets_side_and_quality() -> None:
    d0 = tr.day_start_ms(date(2025, 10, 7))
    rows = [
        (1, "buy", 100.0, 2.0, d0 + 100),
        (2, "sell", 101.0, 1.0, d0 + 4_900),
        (2, "sell", 101.0, 1.0, d0 + 4_900),  # duplicate id
        (3, "buy", 99.0, 50.0, d0 + 5_000),  # second bucket, large (threshold 10)
        (4, "buy", 99.5, 1.0, d0 - 1),  # previous archive day
    ]
    out = tr.reduce_day(_csv(rows), d0, big_threshold=10.0)
    q, a = out["quality"], out["arrays"]
    assert (q["trades"], q["duplicates"], q["outside_day"]) == (3, 1, 1)
    assert a["buy_vol"][0] == pytest.approx(200.0)  # notional = size x price
    assert a["sell_vol"][0] == pytest.approx(101.0)
    assert (a["high"][0], a["low"][0], a["last"][0]) == (101.0, 100.0, 101.0)
    assert a["big_buy"][1] == pytest.approx(99.0 * 50.0) and a["big_buy"][0] == 0.0


def test_archive_day_is_utc_plus_8() -> None:
    assert tr.day_start_ms(date(2025, 10, 7)) == 1759766400000  # 2025-10-06 16:00 UTC


def test_read_day_holdout_locked() -> None:
    with pytest.raises(HoldoutLockedError):
        tr.read_day("ETHUSDT", date(2026, 7, 2))


def test_tradebook_dedupe_gap_and_backfill() -> None:
    b = col.TradeBook(last_id=10)
    assert b.accept(11, live=True) and b.gaps == []
    assert b.accept(15, live=True)
    assert (b.id_jumps, b.missing_ids, b.gaps) == (1, 3, [(11, 15)])
    assert not b.accept(15, live=True) and b.duplicates == 1
    for i in (12, 13, 14):
        assert b.accept(i, live=False)
    assert (b.backfilled, b.missing_ids, b.last_id) == (3, 0, 15)


def test_store_rotates_by_exchange_day_and_appends_members(tmp_path: Path) -> None:
    s = col.Store(tmp_path)
    s.write("oi", "ETHUSDT", 1791417599000, "a")  # 2026-10-07 23:59:59 UTC
    s.write("oi", "ETHUSDT", 1791417600000, "b")  # 2026-10-08 00:00:00 UTC
    s.close()
    s2 = col.Store(tmp_path)  # restart appends a new gzip member, no second header
    s2.write("oi", "ETHUSDT", 1791417601000, "c")
    s2.close()
    day1 = _lines(tmp_path / "oi/ETHUSDT/20261007.csv.gz")
    day2 = _lines(tmp_path / "oi/ETHUSDT/20261008.csv.gz")
    assert day1 == [col.HEADERS["oi"], "a"]
    assert day2 == [col.HEADERS["oi"], "b", "c"]


def _lines(path: Path) -> list[str]:
    with gzip.open(path, "rt") as fh:
        return fh.read().splitlines()


def _msg(channel: str, data: list[dict[str, Any]]) -> dict[str, Any]:
    return {"arg": {"channel": channel, "instId": "ETH-USDT-SWAP"}, "data": data}


def _book(ts: int) -> dict[str, Any]:
    lv = [["100", "1", "0", "1"]] * 5
    return {"instId": "ETH-USDT-SWAP", "ts": str(ts), "seqId": 1, "bids": lv, "asks": lv}


async def test_collector_books_sampled_per_second_and_trades_deduped(tmp_path: Path) -> None:
    c = col.Collector(("ETHUSDT",), tmp_path)
    t0 = 1791417600000
    await c.on_message(_msg("books5", [_book(t0 + 100), _book(t0 + 900), _book(t0 + 1_050)]))
    trade = {"instId": "ETH-USDT-SWAP", "tradeId": "7", "px": "100", "sz": "1", "side": "buy"}
    await c.on_message(_msg("trades-all", [{**trade, "ts": str(t0)}, {**trade, "ts": str(t0)}]))
    c.store.close()
    books = _lines(tmp_path / "books5/ETHUSDT/20261008.csv.gz")
    assert len(books) == 2 and books[1].startswith(f"{t0 + 900},")  # last snapshot of second 0
    trades_rows = _lines(tmp_path / "trades/ETHUSDT/20261008.csv.gz")
    assert len(trades_rows) == 2 and c.trades["ETHUSDT"].duplicates == 1


class _FakeResp:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self._rows = rows

    def json(self) -> dict[str, Any]:
        return {"data": self._rows}


class _FakeClient:
    """history-trades semantics: newest first, `after` = strictly older than that tradeId."""

    def __init__(self, ids: range) -> None:
        self.ids = ids

    async def get(self, url: str, params: dict[str, str]) -> _FakeResp:
        after = int(params["after"])
        older = [i for i in reversed(self.ids) if i < after][: int(params["limit"])]
        rows = [
            {"tradeId": str(i), "ts": "1791417600000", "px": "1", "sz": "1", "side": "buy"}
            for i in older
        ]
        return _FakeResp(rows)


async def test_backfill_fills_gap_exactly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    c = col.Collector(("ETHUSDT",), tmp_path)
    book = c.trades["ETHUSDT"]
    book.last_id = 1000
    book.accept(1250, live=True)  # 249 missing ids
    await c.backfill(_FakeClient(range(900, 1300)), "ETHUSDT")  # type: ignore[arg-type]
    assert (book.backfilled, book.missing_ids, book.gaps) == (249, 0, [])
    assert not (tmp_path / "gaps.jsonl").exists()


async def test_backfill_logs_unfilled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    monkeypatch.setattr(col, "BACKFILL_PAGES", 1)
    c = col.Collector(("ETHUSDT",), tmp_path)
    c.trades["ETHUSDT"].last_id = 1000
    c.trades["ETHUSDT"].accept(1500, live=True)
    await c.backfill(_FakeClient(range(900, 1600)), "ETHUSDT")  # type: ignore[arg-type]
    gap = json.loads((tmp_path / "gaps.jsonl").read_text().splitlines()[-1])
    assert gap["kind"] == "trade_ids_unfilled" and gap["missing"] == 399


async def _no_sleep(_: float) -> None:
    return None


def _synthetic_buckets(n_days: int = 3, seed: int = 5) -> Any:
    import random
    from array import array

    from app.research.micro import stage_ab as ab

    rng = random.Random(seed)  # noqa: S311 - deterministic test data
    n = n_days * tr.PER_DAY
    price, px = 100.0, array("d")
    cols: dict[str, Any] = {
        k: array("d") for k in ("hi", "lo", "buy", "sell", "big_buy", "big_sell")
    }
    for _ in range(n):
        price *= math.exp(rng.gauss(0, 3e-4))
        px.append(price)
        cols["hi"].append(price * 1.0001)
        cols["lo"].append(price * 0.9999)
        b, s = rng.expovariate(1.0), rng.expovariate(1.0)
        cols["buy"].append(b)
        cols["sell"].append(s)
        cols["big_buy"].append(b if rng.random() < 0.05 else 0.0)
        cols["big_sell"].append(s if rng.random() < 0.05 else 0.0)
    return ab.Buckets(0, px, n=array("i", [3] * n), **cols)


def test_stage_ab_features_and_setups_are_causal() -> None:
    """Changing everything after a candle close must not change features or setups at it."""
    from app.research.micro import stage_ab as ab

    b = _synthetic_buckets()
    cut = 2 * tr.PER_DAY  # candle boundary
    full = ab.aggregate(ab.minute_candles(b), 5)
    fr_full = ab.frame(full, None)
    for name in ("price", "hi", "lo", "buy", "sell", "big_buy", "big_sell"):
        arr = getattr(b, name)
        for k in range(cut, len(arr)):
            arr[k] = arr[k] * 1.7 + 1.0
    cut_cd = ab.aggregate(ab.minute_candles(b), 5)
    fr_cut = ab.frame(cut_cd, None)
    last = next(j for j, k in enumerate(full.k_end) if k == cut)
    for feat in ab.FEATURES[:-1]:
        for j in range(ab.WARMUP, last + 1):
            x, y = fr_full.feats[feat][j], fr_cut.feats[feat][j]
            assert (x != x and y != y) or x == pytest.approx(y), (feat, j)
    for j in range(ab.WARMUP, last + 1):
        assert ab.setups(full, fr_full, j) == ab.setups(cut_cd, fr_cut, j)


def test_forward_return_uses_latency_price() -> None:
    from array import array

    from app.research.micro import stage_ab as ab

    px = array("d", [float(i + 1) for i in range(100)])
    zeros = array("d", [0.0] * 100)
    b = ab.Buckets(0, px, px, px, zeros, zeros, zeros, zeros, array("i", [0] * 100))
    # close boundary at bucket 12 (1 minute); +20 s = 4 buckets later; 1 minute after that.
    assert b.px_at(12, 0) == 12.0 and b.px_at(12, 20) == 16.0
    assert ab.fwd(b, 12, 20, 1) == pytest.approx(math.log(28.0 / 16.0))
