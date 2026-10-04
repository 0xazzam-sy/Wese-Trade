from __future__ import annotations

import asyncio
import gzip
import json
from collections.abc import Mapping
from typing import Any

from app.market_data.bingx.stream import BingXMarketStream


class FakeSocket:
    def __init__(self) -> None:
        self.inbox: asyncio.Queue[str | bytes | Exception] = asyncio.Queue()
        self.sent: list[str] = []
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str | bytes:
        item = await self.inbox.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True

    def push(self, payload: Mapping[str, Any] | str) -> None:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        self.inbox.put_nowait(gzip.compress(text.encode()))

    def subs(self) -> list[str]:
        return [
            json.loads(m)["dataType"] for m in self.sent if m.startswith("{") and "reqType" in m
        ]


class Harness:
    def __init__(self, **kwargs: Any) -> None:
        self.sockets: list[FakeSocket] = []
        self.messages: list[Mapping[str, Any]] = []
        self.states: list[str] = []
        self.reconnects = 0

        async def connector(url: str) -> FakeSocket:
            socket = FakeSocket()
            self.sockets.append(socket)
            return socket

        self.stream = BingXMarketStream(
            "wss://example", connector=connector, backoff_base=0.01, backoff_max=0.02, **kwargs
        )

        async def on_message(message: Mapping[str, Any]) -> None:
            self.messages.append(message)

        async def on_state(state: str) -> None:
            self.states.append(state)

        async def on_reconnected() -> None:
            self.reconnects += 1

        self.stream.set_handlers(
            on_message=on_message, on_state=on_state, on_reconnected=on_reconnected
        )


async def wait_for(predicate: Any, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


async def test_ping_pong_and_message_dispatch() -> None:
    h = Harness()
    h.stream.start()
    await wait_for(lambda: h.stream.state == "connected")
    socket = h.sockets[0]
    socket.push("Ping")
    await wait_for(lambda: "Pong" in socket.sent)
    socket.push({"ping": "abc", "time": "t"})
    await wait_for(lambda: any('"pong": "abc"' in m for m in socket.sent))
    socket.push({"code": 0, "dataType": "BTC-USDT@kline_1m", "data": {"c": "1"}})
    socket.inbox.put_nowait(b"\x00garbage")  # malformed frame must not kill the loop
    socket.push({"code": 0, "dataType": "BTC-USDT@kline_1m", "data": {"c": "2"}})
    await wait_for(lambda: len(h.messages) == 2)
    assert h.stream.malformed_count == 1
    await h.stream.close()
    assert h.states[-1] == "disconnected"


async def test_subscriptions_are_idempotent_and_restored_after_reconnect() -> None:
    h = Harness()
    await h.stream.subscribe("BTC-USDT@kline_1m")  # before connect: queued in registry
    h.stream.start()
    await wait_for(lambda: h.stream.state == "connected" and h.sockets[0].subs())
    await h.stream.subscribe("ETH-USDT@kline_5m")
    await h.stream.subscribe("ETH-USDT@kline_5m")  # duplicate ignored
    first = h.sockets[0]
    assert first.subs() == ["BTC-USDT@kline_1m", "ETH-USDT@kline_5m"]

    first.inbox.put_nowait(ConnectionError("dropped"))
    await wait_for(lambda: len(h.sockets) == 2 and h.stream.state == "connected")
    await wait_for(lambda: h.reconnects == 1)
    assert sorted(h.sockets[1].subs()) == ["BTC-USDT@kline_1m", "ETH-USDT@kline_5m"]
    assert h.stream.reconnect_count == 1
    assert "reconnecting" in h.states

    await h.stream.unsubscribe("BTC-USDT@kline_1m")
    assert json.loads(h.sockets[1].sent[-1])["reqType"] == "unsub"
    await h.stream.close()


async def test_silent_socket_is_detected_and_replaced() -> None:
    h = Harness(silence_timeout=0.05)
    h.stream.start()
    await wait_for(lambda: len(h.sockets) >= 2, timeout=3)
    assert h.sockets[0].closed
    await h.stream.close()


async def test_connect_failures_back_off_and_recover() -> None:
    attempts = {"n": 0}
    h = Harness()

    async def flaky(url: str) -> FakeSocket:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise OSError("refused")
        socket = FakeSocket()
        h.sockets.append(socket)
        return socket

    h.stream._connector = flaky
    h.stream.start()
    await wait_for(lambda: h.stream.state == "connected")
    assert attempts["n"] == 3
    await h.stream.close()


async def test_rejected_subscription_is_recorded() -> None:
    h = Harness()
    h.stream.start()
    await wait_for(lambda: h.stream.state == "connected")
    h.sockets[0].push({"id": "1", "code": 80015, "msg": "bad", "dataType": "NOPE-USDT@kline_1m"})
    await wait_for(lambda: "NOPE-USDT@kline_1m" in h.stream.failed_subscriptions)
    await h.stream.close()
