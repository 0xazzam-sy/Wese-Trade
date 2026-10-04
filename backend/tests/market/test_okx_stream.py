from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from typing import Any

from app.market_data.okx.stream import OkxSocket


class FakeSocket:
    def __init__(self) -> None:
        self.inbox: asyncio.Queue[str | Exception] = asyncio.Queue()
        self.sent: list[str] = []
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(message)

    async def recv(self) -> str:
        item = await self.inbox.get()
        if isinstance(item, Exception):
            raise item
        return item

    async def close(self) -> None:
        self.closed = True
        self.inbox.put_nowait(ConnectionError("closed"))

    def push(self, payload: Mapping[str, Any] | str) -> None:
        self.inbox.put_nowait(payload if isinstance(payload, str) else json.dumps(payload))

    def requests(self) -> list[dict[str, Any]]:
        return [json.loads(m) for m in self.sent if m.startswith("{")]


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

        defaults: dict[str, Any] = {"backoff_base": 0.01, "backoff_max": 0.02, "debounce": 0.01}
        self.socket = OkxSocket(
            "business", "wss://example", connector=connector, **{**defaults, **kwargs}
        )

        async def on_message(message: Mapping[str, Any]) -> None:
            self.messages.append(message)

        async def on_state(state: str) -> None:
            self.states.append(state)

        async def on_reconnected() -> None:
            self.reconnects += 1

        self.socket.set_handlers(
            on_message=on_message, on_state=on_state, on_reconnected=on_reconnected
        )


async def wait_for(predicate: Any, timeout: float = 2.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.005)


async def test_data_dispatch_acks_and_malformed_frames() -> None:
    h = Harness()
    h.socket.start()
    await wait_for(lambda: h.socket.state == "connected")
    s = h.sockets[0]
    s.push({"event": "subscribe", "arg": {"channel": "candle1m", "instId": "BTC-USDT-SWAP"}})
    s.push("not json")
    s.push({"arg": {"channel": "candle1m", "instId": "BTC-USDT-SWAP"}, "data": [["1"]]})
    await wait_for(lambda: len(h.messages) == 1)
    assert h.socket.malformed_count == 1
    await h.socket.close()
    assert h.states[-1] == "disconnected"


async def test_text_ping_after_silence_and_reconnect_without_pong() -> None:
    h = Harness(ping_after=0.05, pong_timeout=0.05)
    h.socket.start()
    await wait_for(lambda: "ping" in (h.sockets[0].sent if h.sockets else []))
    h.sockets[0].push("pong")  # answered: connection stays
    await asyncio.sleep(0.03)
    assert len(h.sockets) == 1
    # No answer to the next ping -> heartbeat timeout -> new connection.
    await wait_for(lambda: len(h.sockets) == 2, timeout=3)
    assert h.socket.reconnect_count >= 1
    await h.socket.close()


async def test_subscriptions_are_batched_debounced_and_restored() -> None:
    h = Harness()
    h.socket.subscribe("candle1m", "BTC-USDT-SWAP")  # before connect: kept in registry
    h.socket.start()
    await wait_for(lambda: h.socket.state == "connected" and h.sockets[0].requests())
    first = h.sockets[0]
    # A burst of changes is coalesced into one subscribe request.
    h.socket.subscribe("candle5m", "ETH-USDT-SWAP")
    h.socket.subscribe("candle5m", "ETH-USDT-SWAP")
    h.socket.subscribe("candle1H", "SOL-USDT-SWAP")
    h.socket.subscribe("candle15m", "XRP-USDT-SWAP")
    h.socket.unsubscribe("candle15m", "XRP-USDT-SWAP")  # net zero: never sent
    await wait_for(lambda: len(first.requests()) == 2)
    second = first.requests()[1]
    assert second["op"] == "subscribe"
    assert second["args"] == [
        {"channel": "candle1H", "instId": "SOL-USDT-SWAP"},
        {"channel": "candle5m", "instId": "ETH-USDT-SWAP"},
    ]
    assert h.socket.request_count == 2

    first.inbox.put_nowait(ConnectionError("dropped"))
    await wait_for(lambda: len(h.sockets) == 2 and h.socket.state == "connected")
    await wait_for(lambda: h.reconnects == 1)
    restored = h.sockets[1].requests()
    assert len(restored) == 1  # one batched request restores everything
    assert {a["instId"] for a in restored[0]["args"]} == {
        "BTC-USDT-SWAP",
        "ETH-USDT-SWAP",
        "SOL-USDT-SWAP",
    }

    h.socket.unsubscribe("candle1m", "BTC-USDT-SWAP")
    await wait_for(lambda: len(h.sockets[1].requests()) == 2)
    assert h.sockets[1].requests()[1] == {
        "op": "unsubscribe",
        "args": [{"channel": "candle1m", "instId": "BTC-USDT-SWAP"}],
    }
    await h.socket.close()


async def test_rejected_subscription_recorded_and_notice_triggers_reconnect() -> None:
    h = Harness()
    h.socket.start()
    await wait_for(lambda: h.socket.state == "connected")
    h.sockets[0].push(
        {
            "event": "error",
            "code": "60018",
            "msg": "bad",
            "arg": {"channel": "candle1m", "instId": "NOPE-USDT-SWAP"},
        }
    )
    await wait_for(lambda: ("candle1m", "NOPE-USDT-SWAP") in h.socket.failed_subscriptions)
    h.sockets[0].push({"event": "notice", "code": "64008", "msg": "service upgrade"})
    await wait_for(lambda: len(h.sockets) == 2)
    await h.socket.close()


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

    h.socket._connector = flaky
    h.socket.start()
    await wait_for(lambda: h.socket.state == "connected")
    assert attempts["n"] == 3
    await h.socket.close()
