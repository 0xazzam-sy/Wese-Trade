"""Phase 8 live microstructure collector (prospective data; docs/research-microscalp.md §2).

Feeds (OKX public, no credentials):
    trades-all          every individual trade with aggressor side (business socket)
    books5              top-5 L2 snapshot, sampled to the last snapshot of each exchange second
    open-interest       per instrument (~3 s)
    funding-rate        per instrument
    liquidation-orders  all USDT swaps (instType SWAP)

Robustness:
    - reconnect with backoff, heartbeat and full resubscribe (shared OkxSocket client)
    - trade dedupe by tradeId (live/backfill overlap, restarts), out-of-order and id-jump counts
    - after every reconnect and on restart: REST backfill of missed trades (history-trades)
    - gap log (disconnect intervals, unfilled trade-id ranges, stale feeds) in gaps.jsonl
    - exchange timestamps are stored with the local receive time; rotation by exchange UTC day
    - append-only gzip CSV per stream/symbol/day (a restart adds a new gzip member)
    - health.json every 10 s; state.json (last tradeId per instrument) for restarts

Nothing goes into the application database. This is research/prospective data only.

    python -m app.research.micro.collector run [--symbols BTCUSDT,ETHUSDT] [--root DIR]
    python -m app.research.micro.collector health [--root DIR]
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import gzip
import json
import signal
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any

import httpx

from app.core.config import get_settings
from app.market_data.okx.stream import OkxSocket
from app.research.micro.trades import inst_id
from app.research.store import RESEARCH_DIR

ROOT = RESEARCH_DIR / "micro" / "live"
SYMBOLS = (
    "BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT", "HYPEUSDT",
    "NEARUSDT", "UNIUSDT", "PUMPUSDT", "SUIUSDT", "PEPEUSDT", "ARBUSDT",
)  # fmt: skip
REST = "https://www.okx.com/api/v5/market/history-trades"
HEALTH_EVERY = 10.0
STALE_AFTER_MS = {"trades": 120_000, "books5": 15_000, "oi": 60_000, "funding": 300_000}
BACKFILL_PAGES = 30  # 100 trades per page
RECENT_IDS = 20_000

HEADERS = {
    "trades": "ts,trade_id,px,sz,side,recv_ms,src",
    "books5": "ts,seq,bid_px1,bid_sz1,bid_px2,bid_sz2,bid_px3,bid_sz3,bid_px4,bid_sz4,bid_px5,"
    "bid_sz5,ask_px1,ask_sz1,ask_px2,ask_sz2,ask_px3,ask_sz3,ask_px4,ask_sz4,ask_px5,ask_sz5,"
    "recv_ms",
    "oi": "ts,oi,oi_ccy,oi_usd,recv_ms",
    "funding": "ts,funding_rate,funding_time,premium,recv_ms",
    "liquidations": "ts,inst,side,pos_side,bk_px,sz,bk_loss,recv_ms",
}


def now_ms() -> int:
    return int(time.time() * 1000)


def day_of(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, UTC).strftime("%Y%m%d")


class Store:
    """Append-only gzip CSV files rotated by exchange UTC day."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._files: dict[tuple[str, str, str], IO[str]] = {}
        self.rows = 0

    def write(self, stream: str, symbol: str, ts_ms: int, row: str) -> None:
        key = (stream, symbol, day_of(ts_ms))
        fh = self._files.get(key)
        if fh is None:
            path = self.root / stream / symbol / f"{key[2]}.csv.gz"
            path.parent.mkdir(parents=True, exist_ok=True)
            new = not path.exists()
            fh = gzip.open(path, "at", encoding="ascii", compresslevel=6)  # noqa: SIM115
            if new:
                fh.write(HEADERS[stream] + "\n")
            self._files[key] = fh
            self._retire(key)
        fh.write(row + "\n")
        self.rows += 1

    def _retire(self, current: tuple[str, str, str]) -> None:
        """Close files more than one day older than the newest one for the same stream."""
        for key in [
            k for k in self._files if k[:2] == current[:2] and k[2] < current[2] and k != current
        ]:
            others = sorted(k[2] for k in self._files if k[:2] == current[:2])
            if len(others) > 2 and key[2] == others[0]:
                self._files.pop(key).close()

    def flush(self) -> None:
        for fh in self._files.values():
            fh.flush()

    def close(self) -> None:
        for fh in self._files.values():
            fh.close()
        self._files.clear()


@dataclass
class Feed:
    msgs: int = 0
    last_ts: int = 0  # exchange time of the newest record
    last_recv: int = 0
    lag_ms: float = 0.0  # EWMA of receive - exchange time
    max_silence_ms: int = 0
    stale_events: int = 0
    stale: bool = False

    def seen(self, ts: int, recv: int) -> None:
        if self.last_recv:
            self.max_silence_ms = max(self.max_silence_ms, recv - self.last_recv)
        self.msgs += 1
        self.last_ts = max(self.last_ts, ts)
        self.last_recv = recv
        self.lag_ms = (recv - ts) if self.msgs == 1 else 0.98 * self.lag_ms + 0.02 * (recv - ts)
        self.stale = False


@dataclass
class TradeBook:
    last_id: int = 0
    recent: set[int] = field(default_factory=set)
    order: deque[int] = field(default_factory=deque)
    duplicates: int = 0
    out_of_order: int = 0
    id_jumps: int = 0
    missing_ids: int = 0
    backfilled: int = 0
    gaps: list[tuple[int, int]] = field(default_factory=list)  # open (exclusive) id ranges

    def accept(self, tid: int, *, live: bool) -> bool:
        if tid in self.recent:
            self.duplicates += 1
            return False
        self.recent.add(tid)
        self.order.append(tid)
        if len(self.order) > RECENT_IDS:
            self.recent.discard(self.order.popleft())
        if tid > self.last_id:
            if live and self.last_id and tid > self.last_id + 1:
                self.id_jumps += 1
                self.missing_ids += tid - self.last_id - 1
                self.gaps.append((self.last_id, tid))
            self.last_id = tid
        elif live:
            self.out_of_order += 1
        else:
            self.backfilled += 1
            self.missing_ids = max(0, self.missing_ids - 1)
        return True


class Collector:
    def __init__(self, symbols: tuple[str, ...], root: Path) -> None:
        self.symbols = symbols
        self.root = root
        self.store = Store(root)
        self.feeds: dict[tuple[str, str], Feed] = {}
        self.trades: dict[str, TradeBook] = {s: TradeBook() for s in symbols}
        self._book_hold: dict[str, tuple[int, str]] = {}
        settings = get_settings()
        self.public = OkxSocket("micro-public", settings.okx_public_ws_url)
        self.business = OkxSocket("micro-business", settings.okx_business_ws_url)
        self._down_since: dict[str, int] = {}
        self._backfill_lock = asyncio.Lock()
        self._stop = asyncio.Event()
        self.started_ms = now_ms()

    # --- persistence ------------------------------------------------------------
    def _gap(self, kind: str, **fields: Any) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / "gaps.jsonl").open("a") as fh:
            fh.write(json.dumps({"logged_ms": now_ms(), "kind": kind, **fields}) + "\n")

    def _load_state(self) -> None:
        path = self.root / "state.json"
        if path.exists():
            state = json.loads(path.read_text())
            for sym, tid in state.get("last_trade_id", {}).items():
                if sym in self.trades:
                    self.trades[sym].last_id = int(tid)

    def _save_state(self) -> None:
        state = {
            "saved_ms": now_ms(),
            "last_trade_id": {s: b.last_id for s, b in self.trades.items()},
        }
        tmp = self.root / "state.json.tmp"
        tmp.write_text(json.dumps(state))
        tmp.replace(self.root / "state.json")

    def health(self) -> dict[str, Any]:
        t = now_ms()
        feeds = {}
        for (stream, sym), f in sorted(self.feeds.items()):
            limit = STALE_AFTER_MS.get(stream)
            if limit and f.last_recv and t - f.last_recv > limit and not f.stale:
                f.stale = True
                f.stale_events += 1
                self._gap("stale", stream=stream, symbol=sym, silent_ms=t - f.last_recv)
            feeds[f"{stream}:{sym}"] = {
                "msgs": f.msgs,
                "last_exchange_ts": f.last_ts,
                "age_ms": t - f.last_recv if f.last_recv else None,
                "lag_ms": round(f.lag_ms, 1),
                "max_silence_ms": f.max_silence_ms,
                "stale": f.stale,
                "stale_events": f.stale_events,
            }
        return {
            "now_ms": t,
            "uptime_s": round((t - self.started_ms) / 1000),
            "rows_written": self.store.rows,
            "sockets": {
                s.name: {
                    "state": s.state,
                    "reconnects": s.reconnect_count,
                    "malformed": s.malformed_count,
                    "failed_subscriptions": sorted(map(list, s.failed_subscriptions)),
                }
                for s in (self.public, self.business)
            },
            "trades": {
                s: {
                    "last_id": b.last_id,
                    "duplicates": b.duplicates,
                    "out_of_order": b.out_of_order,
                    "id_jumps": b.id_jumps,
                    "missing_ids": b.missing_ids,
                    "backfilled": b.backfilled,
                }
                for s, b in self.trades.items()
            },
            "feeds": feeds,
            "ok": all(s.state == "connected" for s in (self.public, self.business))
            and not any(v["stale"] for v in feeds.values()),
        }

    def _write_health(self) -> None:
        self.store.flush()
        self._save_state()
        tmp = self.root / "health.json.tmp"
        tmp.write_text(json.dumps(self.health(), indent=1))
        tmp.replace(self.root / "health.json")

    # --- message handling -------------------------------------------------------
    def _feed(self, stream: str, sym: str) -> Feed:
        f = self.feeds.get((stream, sym))
        if f is None:
            f = self.feeds[(stream, sym)] = Feed()
        return f

    def _trade(self, sym: str, d: Mapping[str, Any], recv: int, src: str) -> int:
        tid = int(d["tradeId"])
        ts = int(d["ts"])
        if not self.trades[sym].accept(tid, live=src == "ws"):
            return 0
        if src == "ws":
            self._feed("trades", sym).seen(ts, recv)
        self.store.write(
            "trades", sym, ts, f"{ts},{tid},{d['px']},{d['sz']},{d['side']},{recv},{src}"
        )
        return 1

    def _book(self, sym: str, d: Mapping[str, Any], recv: int) -> None:
        ts = int(d["ts"])
        self._feed("books5", sym).seen(ts, recv)
        levels: list[str] = []
        for side in ("bids", "asks"):
            rows = list(d.get(side) or [])[:5]
            for i in range(5):
                levels.extend(rows[i][:2] if i < len(rows) else ("", ""))
        row = f"{ts},{d.get('seqId', '')}," + ",".join(levels) + f",{recv}"
        held = self._book_hold.get(sym)
        if held is not None and held[0] // 1000 != ts // 1000:
            self.store.write("books5", sym, held[0], held[1])
        self._book_hold[sym] = (ts, row)

    async def on_message(self, message: Mapping[str, Any]) -> None:
        recv = now_ms()
        channel = message["arg"]["channel"]
        for d in message["data"]:
            if channel == "liquidation-orders":
                inst = str(d.get("instId", ""))
                for x in d.get("details") or []:
                    ts = int(x["ts"])
                    sym = inst.replace("-USDT-SWAP", "USDT") if inst.endswith("-USDT-SWAP") else ""
                    if not sym:
                        continue
                    self._feed("liquidations", "ALL").seen(ts, recv)
                    self.store.write(
                        "liquidations", "ALL", ts,
                        f"{ts},{inst},{x.get('side')},{x.get('posSide')},{x.get('bkPx')},"
                        f"{x.get('sz')},{x.get('bkLoss', '')},{recv}",
                    )  # fmt: skip
                continue
            sym = str(d.get("instId", "")).replace("-USDT-SWAP", "USDT")
            if sym not in self.trades:
                continue
            if channel == "trades-all":
                self._trade(sym, d, recv, "ws")
            elif channel == "books5":
                self._book(sym, d, recv)
            elif channel == "open-interest":
                ts = int(d["ts"])
                self._feed("oi", sym).seen(ts, recv)
                self.store.write(
                    "oi",
                    sym,
                    ts,
                    f"{ts},{d['oi']},{d.get('oiCcy', '')},{d.get('oiUsd', '')},{recv}",
                )
            elif channel == "funding-rate":
                ts = int(d["ts"])
                self._feed("funding", sym).seen(ts, recv)
                self.store.write(
                    "funding", sym, ts,
                    f"{ts},{d.get('fundingRate')},{d.get('fundingTime')},"
                    f"{d.get('premium', '')},{recv}",
                )  # fmt: skip

    async def on_state(self, name: str, state: str) -> None:
        if state == "connected":
            down = self._down_since.pop(name, None)
            if down is not None:
                self._gap("disconnect", socket=name, from_ms=down, to_ms=now_ms())
        elif state in ("reconnecting", "disconnected") and name not in self._down_since:
            self._down_since[name] = now_ms()

    # --- REST backfill ----------------------------------------------------------
    async def backfill(self, client: httpx.AsyncClient, sym: str) -> None:
        """Fill every open trade-id gap from REST history-trades, paging back from its top."""
        book = self.trades[sym]
        gaps, book.gaps = book.gaps, []
        for lo, hi in gaps:
            cursor = str(hi)
            got: list[Mapping[str, Any]] = []
            reached = False
            for _ in range(BACKFILL_PAGES):
                params = {"instId": inst_id(sym), "type": "1", "limit": "100", "after": cursor}
                try:
                    r = await client.get(REST, params=params)
                    rows = r.json().get("data") or []
                except (httpx.HTTPError, ValueError):
                    break
                if not rows:
                    break
                got.extend(rows)
                cursor = rows[-1]["tradeId"]
                if int(cursor) <= lo + 1:
                    reached = True
                    break
                await asyncio.sleep(0.25)  # history-trades: 20 requests / 2 s
            recv = now_ms()
            filled = 0
            for d in sorted(got, key=lambda x: int(x["tradeId"])):
                if lo < int(d["tradeId"]) < hi:
                    filled += self._trade(sym, d, recv, "rest")
            if not reached or filled < hi - lo - 1:
                self._gap("trade_ids_unfilled", symbol=sym, from_id=lo, to_id=hi,
                          missing=hi - lo - 1 - filled)  # fmt: skip

    async def backfill_all(self) -> None:
        if self._backfill_lock.locked() or not any(b.gaps for b in self.trades.values()):
            return
        async with self._backfill_lock:
            await asyncio.sleep(3.0)  # let REST history catch up with the live stream
            async with httpx.AsyncClient(timeout=10.0) as client:
                for sym in self.symbols:
                    await self.backfill(client, sym)

    # --- run --------------------------------------------------------------------
    async def run(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._load_state()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with contextlib.suppress(NotImplementedError):
                loop.add_signal_handler(sig, self._stop.set)
        background: set[asyncio.Task[None]] = set()

        def spawn() -> None:
            task = asyncio.create_task(self.backfill_all())
            background.add(task)
            task.add_done_callback(background.discard)

        async def reconnected() -> None:
            spawn()

        for sock in (self.public, self.business):

            async def state(s: str, n: str = sock.name) -> None:
                await self.on_state(n, s)

            sock.set_handlers(on_message=self.on_message, on_state=state,
                              on_reconnected=reconnected)  # fmt: skip
        for sym in self.symbols:
            inst = inst_id(sym)
            self.business.subscribe("trades-all", inst)
            for ch in ("books5", "open-interest", "funding-rate"):
                self.public.subscribe(ch, inst)
        self.public.subscribe("liquidation-orders", "SWAP")
        self.public.start()
        self.business.start()
        self._gap("start", symbols=list(self.symbols))
        spawn()  # restart: fill trades missed while the collector was down
        try:
            while not self._stop.is_set():
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), HEALTH_EVERY)
                self._write_health()
                spawn()  # fill trade-id gaps (reconnects, restarts)
        finally:
            for t in list(background):
                t.cancel()
            await self.public.close()
            await self.business.close()
            for sym, (ts, row) in self._book_hold.items():
                self.store.write("books5", sym, ts, row)
            self._write_health()
            self.store.close()
            self._gap("stop")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("command", choices=["run", "health"])
    p.add_argument("--symbols", default=",".join(SYMBOLS))
    p.add_argument("--root", default=str(ROOT))
    a = p.parse_args()
    root = Path(a.root)
    if a.command == "health":
        print((root / "health.json").read_text())
        return
    asyncio.run(Collector(tuple(a.symbols.split(",")), root).run())


if __name__ == "__main__":
    main()
