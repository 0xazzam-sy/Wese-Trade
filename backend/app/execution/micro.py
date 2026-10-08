"""Live microstructure for execution quality (books5 + trades, OKX public WebSocket).

Reference-counted per symbol: only symbols with a viewed 1m / 5m / 10m execution stream are
subscribed. Everything here is optional: when the feed is down or stale the execution
engine falls back to candle / structure logic (and refuses NEW confirmations while the
order book is severely stale). No credentials, no orders.
"""

from __future__ import annotations

import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from app.execution.models import Micro
from app.market_data.okx.stream import OkxSocket

FLOW_WINDOW_S = 60.0
DEGRADED_BOOK_AGE_S = 5.0
STALE_BOOK_AGE_S = 15.0
SPREAD_ABNORMAL = 3.0
NORMAL_ALPHA = 0.01


def inst_id(symbol: str) -> str:
    return symbol.replace("USDT", "-USDT-SWAP") if symbol.endswith("USDT") else symbol


@dataclass(slots=True)
class _Book:
    ts: float = 0.0  # local receive time (monotonic)
    spread_bp: float | None = None
    normal_bp: float | None = None
    imbalance: float | None = None
    trades: deque[tuple[float, float]] = field(
        default_factory=deque
    )  # (monotonic, signed notional)
    last_trade: float = 0.0


class MicroFeed:
    def __init__(
        self,
        url: str,
        *,
        socket_factory: Callable[[str, str], Any] = OkxSocket,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._url = url
        self._factory = socket_factory
        self._clock = clock
        self._socket: Any = None
        self._refs: dict[str, int] = {}
        self._books: dict[str, _Book] = {}
        self.messages = 0

    # --- subscriptions --------------------------------------------------------------------
    def acquire(self, symbol: str) -> None:
        self._refs[symbol] = self._refs.get(symbol, 0) + 1
        if self._refs[symbol] > 1:
            return
        sock = self._ensure()
        inst = inst_id(symbol)
        sock.subscribe("books5", inst)
        sock.subscribe("trades", inst)

    def release(self, symbol: str) -> None:
        n = self._refs.get(symbol, 0) - 1
        if n > 0:
            self._refs[symbol] = n
            return
        self._refs.pop(symbol, None)
        self._books.pop(symbol, None)
        if self._socket is not None:
            inst = inst_id(symbol)
            self._socket.unsubscribe("books5", inst)
            self._socket.unsubscribe("trades", inst)

    def _ensure(self) -> Any:
        if self._socket is None:
            self._socket = self._factory("execution-micro", self._url)

            async def on_message(message: Mapping[str, Any]) -> None:
                self.on_message(message)

            async def on_state(_state: str) -> None:
                return None

            async def on_reconnected() -> None:
                return None

            self._socket.set_handlers(
                on_message=on_message, on_state=on_state, on_reconnected=on_reconnected
            )
            self._socket.start()
        return self._socket

    async def close(self) -> None:
        if self._socket is not None:
            await self._socket.close()
            self._socket = None

    # --- data -----------------------------------------------------------------------------
    def on_message(self, message: Mapping[str, Any]) -> None:
        channel = message.get("arg", {}).get("channel")
        now = self._clock()
        for d in message.get("data") or ():
            symbol = str(d.get("instId", "")).replace("-USDT-SWAP", "USDT")
            if symbol not in self._refs:
                continue
            book = self._books.setdefault(symbol, _Book())
            self.messages += 1
            try:
                if channel == "books5":
                    self._on_book(book, d, now)
                elif channel == "trades":
                    signed = float(d["sz"]) * float(d["px"]) * (1 if d.get("side") == "buy" else -1)
                    book.trades.append((now, signed))
                    book.last_trade = now
            except (KeyError, TypeError, ValueError, IndexError):
                continue

    @staticmethod
    def _on_book(book: _Book, d: Mapping[str, Any], now: float) -> None:
        bids, asks = d.get("bids") or [], d.get("asks") or []
        if not bids or not asks:
            return
        bb, ba = float(bids[0][0]), float(asks[0][0])
        if bb <= 0 or ba <= bb:
            return
        mid = (bb + ba) / 2
        spread = (ba - bb) / mid * 1e4
        b5 = sum(float(x[1]) for x in bids[:5])
        a5 = sum(float(x[1]) for x in asks[:5])
        book.ts = now
        book.spread_bp = spread
        book.normal_bp = (
            spread
            if book.normal_bp is None
            else book.normal_bp + NORMAL_ALPHA * (spread - book.normal_bp)
        )
        book.imbalance = (b5 - a5) / (b5 + a5) if b5 + a5 > 0 else 0.0

    def snapshot(self, symbol: str) -> Micro:
        book = self._books.get(symbol)
        connected = self._socket is not None and getattr(self._socket, "state", "") == "connected"
        if book is None or book.spread_bp is None:
            return Micro(status="unavailable", reasons=("لا توجد بيانات سوق لحظية بعد",))
        now = self._clock()
        while book.trades and now - book.trades[0][0] > FLOW_WINDOW_S:
            book.trades.popleft()
        buy = sum(v for _, v in book.trades if v > 0)
        sell = -sum(v for _, v in book.trades if v < 0)
        flow = (buy - sell) / (buy + sell) if buy + sell > 0 else None
        age = now - book.ts
        reasons: list[str] = []
        if not connected or age > STALE_BOOK_AGE_S:
            status = "stale"
            reasons.append("دفتر الأوامر متأخر")
        elif age > DEGRADED_BOOK_AGE_S or (
            book.normal_bp and book.spread_bp > SPREAD_ABNORMAL * book.normal_bp
        ):
            status = "degraded"
            reasons.append("فارق سعري غير طبيعي" if age <= DEGRADED_BOOK_AGE_S else "تأخر طفيف")
        else:
            status = "ok"
        return Micro(
            status=status,
            spread_bp=round(book.spread_bp, 3),
            spread_normal_bp=round(book.normal_bp, 3) if book.normal_bp else None,
            book_imbalance=round(book.imbalance, 3) if book.imbalance is not None else None,
            flow_imbalance=round(flow, 3) if flow is not None else None,
            book_age_s=round(age, 1),
            trade_age_s=round(now - book.last_trade, 1) if book.last_trade else None,
            reasons=tuple(reasons),
        )

    def health(self) -> dict[str, Any]:
        return {
            "symbols": sorted(self._refs),
            "socket": getattr(self._socket, "state", "idle") if self._socket else "idle",
            "messages": self.messages,
            "status": {s: self.snapshot(s).status for s in self._refs},
        }
