"""One shared OKX public WebSocket connection (instantiated once per endpoint:
`/ws/v5/public` and `/ws/v5/business`). Never one socket per chart or browser.

- connect / reconnect with exponential backoff + jitter, clean shutdown
- subscription registry of (channel, instId); sub/unsub bursts are debounced and batched
  (OKX limits subscribe/unsubscribe requests to 480 per connection per hour)
- full resubscribe after every reconnect
- heartbeat: after PING_AFTER seconds of silence send text "ping"; if nothing (not even
  "pong") arrives within PONG_TIMEOUT the socket is treated as dead and replaced
- malformed frames are logged at DEBUG and counted, never fatal
- OKX "notice" events (e.g. planned service upgrade) trigger a proactive reconnect
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from app.core.logging import get_logger
from app.market_data.okx.constants import (
    WS_BACKOFF_BASE_SECONDS,
    WS_BACKOFF_MAX_SECONDS,
    WS_OPEN_TIMEOUT_SECONDS,
    WS_PING_AFTER_SECONDS,
    WS_PONG_TIMEOUT_SECONDS,
    WS_SUBSCRIBE_BATCH,
    WS_SUBSCRIBE_DEBOUNCE_SECONDS,
)

logger = get_logger(__name__)

Arg = tuple[str, str]  # (channel, instId)


class WebSocketLike(Protocol):
    async def send(self, message: str) -> None: ...

    async def recv(self) -> str | bytes: ...

    async def close(self) -> None: ...


Connector = Callable[[str], Awaitable[WebSocketLike]]
MessageHandler = Callable[[Mapping[str, Any]], Awaitable[None]]
StateHandler = Callable[[str], Awaitable[None]]
ReconnectHandler = Callable[[], Awaitable[None]]


async def default_connector(url: str) -> WebSocketLike:
    from websockets.asyncio.client import connect

    # OKX uses an application-level text "ping"/"pong" heartbeat; protocol pings are off.
    return await connect(
        url,
        open_timeout=WS_OPEN_TIMEOUT_SECONDS,
        ping_interval=None,
        max_size=2**22,
        close_timeout=5,
    )


def _arg_json(arg: Arg) -> dict[str, str]:
    return {"channel": arg[0], "instId": arg[1]}


class OkxSocket:
    def __init__(
        self,
        name: str,
        url: str,
        *,
        connector: Connector = default_connector,
        ping_after: float = WS_PING_AFTER_SECONDS,
        pong_timeout: float = WS_PONG_TIMEOUT_SECONDS,
        backoff_base: float = WS_BACKOFF_BASE_SECONDS,
        backoff_max: float = WS_BACKOFF_MAX_SECONDS,
        debounce: float = WS_SUBSCRIBE_DEBOUNCE_SECONDS,
    ) -> None:
        self.name = name
        self._url = url
        self._connector = connector
        self._ping_after = ping_after
        self._pong_timeout = pong_timeout
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._debounce = debounce
        self._subscriptions: set[Arg] = set()
        self._sent: set[Arg] = set()  # what the server currently has (this connection)
        self._socket: WebSocketLike | None = None
        self._task: asyncio.Task[None] | None = None
        self._flush_task: asyncio.Task[None] | None = None
        self._closing = False
        self._send_lock = asyncio.Lock()
        self._on_message: MessageHandler | None = None
        self._on_state: StateHandler | None = None
        self._on_reconnected: ReconnectHandler | None = None
        self._background: set[asyncio.Task[None]] = set()

        self.state = "disconnected"
        self.reconnect_count = 0
        self.last_message_monotonic: float | None = None
        self.malformed_count = 0
        self.request_count = 0
        self.failed_subscriptions: set[Arg] = set()

    def set_handlers(
        self,
        *,
        on_message: MessageHandler,
        on_state: StateHandler,
        on_reconnected: ReconnectHandler,
    ) -> None:
        self._on_message = on_message
        self._on_state = on_state
        self._on_reconnected = on_reconnected

    @property
    def subscriptions(self) -> frozenset[Arg]:
        return frozenset(self._subscriptions)

    # --- lifecycle ------------------------------------------------------------
    def start(self) -> None:
        if self._task is None:
            self._closing = False
            self._task = asyncio.create_task(self._run(), name=f"okx-{self.name}-socket")

    async def close(self) -> None:
        self._closing = True
        for task in (self._flush_task, *self._background):
            if task is not None:
                task.cancel()
        socket = self._socket
        if socket is not None:
            with contextlib.suppress(Exception):
                await socket.close()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._set_state("disconnected")

    async def drop_connection(self) -> None:
        """Close the current socket (the run loop reconnects). Used for planned reconnects."""
        socket = self._socket
        if socket is not None:
            with contextlib.suppress(Exception):
                await socket.close()

    # --- subscriptions (debounced) -------------------------------------------
    def subscribe(self, channel: str, inst_id: str) -> None:
        self._subscriptions.add((channel, inst_id))
        self.failed_subscriptions.discard((channel, inst_id))
        self._schedule_flush()

    def unsubscribe(self, channel: str, inst_id: str) -> None:
        self._subscriptions.discard((channel, inst_id))
        self._schedule_flush()

    def _schedule_flush(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.create_task(self._flush_later())

    async def _flush_later(self) -> None:
        await asyncio.sleep(self._debounce)
        await self._flush()

    async def _flush(self) -> None:
        """Reconcile the server-side set with the registry using as few requests as possible."""
        if self._socket is None or self.state != "connected":
            return
        to_sub = sorted(self._subscriptions - self._sent)
        to_unsub = sorted(self._sent - self._subscriptions)
        for op, args in (("unsubscribe", to_unsub), ("subscribe", to_sub)):
            for i in range(0, len(args), WS_SUBSCRIBE_BATCH):
                batch = args[i : i + WS_SUBSCRIBE_BATCH]
                await self._send(json.dumps({"op": op, "args": [_arg_json(a) for a in batch]}))
                self.request_count += 1
        self._sent = (self._sent | set(to_sub)) - set(to_unsub)

    async def _send(self, text: str) -> None:
        socket = self._socket
        if socket is None:
            return
        async with self._send_lock:
            try:
                await socket.send(text)
            except Exception as exc:  # socket died; the read loop reconnects
                logger.debug(
                    "okx.ws_send_failed", extra={"fields": {"socket": self.name, "error": str(exc)}}
                )

    # --- main loop -------------------------------------------------------------
    async def _run(self) -> None:
        attempt = 0
        has_connected = False
        while not self._closing:
            await self._set_state("reconnecting" if has_connected else "connecting")
            try:
                self._socket = await self._connector(self._url)
            except Exception as exc:
                logger.warning(
                    "okx.ws_connect_failed",
                    extra={"fields": {"socket": self.name, "error": str(exc)}},
                )
                await self._backoff(attempt)
                attempt += 1
                continue

            attempt = 0
            self._sent = set()
            self.last_message_monotonic = time.monotonic()
            await self._set_state("connected")
            logger.info(
                "okx.ws_connected",
                extra={
                    "fields": {
                        "socket": self.name,
                        "reconnects": self.reconnect_count,
                        "subscriptions": len(self._subscriptions),
                    }
                },
            )
            await self._flush()
            if has_connected:
                logger.info(
                    "okx.ws_resubscribed",
                    extra={
                        "fields": {"socket": self.name, "subscriptions": len(self._subscriptions)}
                    },
                )
                self._spawn(self._notify_reconnected())
            has_connected = True

            reason = await self._read_loop()
            socket, self._socket = self._socket, None
            if socket is not None:
                with contextlib.suppress(Exception):
                    await socket.close()
            if self._closing:
                break
            self.reconnect_count += 1
            logger.warning(
                "okx.ws_disconnected", extra={"fields": {"socket": self.name, "reason": reason}}
            )
            await self._set_state("reconnecting")
            await self._backoff(0)

    async def _read_loop(self) -> str:
        socket = self._socket
        if socket is None:
            return "no_socket"
        awaiting_pong = False
        while not self._closing:
            timeout = self._pong_timeout if awaiting_pong else self._ping_after
            try:
                frame = await asyncio.wait_for(socket.recv(), timeout=timeout)
            except TimeoutError:
                if awaiting_pong:
                    return "heartbeat_timeout"
                await self._send("ping")
                awaiting_pong = True
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return f"closed: {type(exc).__name__}"
            awaiting_pong = False
            self.last_message_monotonic = time.monotonic()
            if await self._handle_frame(frame):
                return "server_notice"
        return "closing"

    async def _handle_frame(self, frame: str | bytes) -> bool:
        """Returns True when the connection should be recycled."""
        text = frame.decode("utf-8", errors="replace") if isinstance(frame, bytes) else frame
        if text == "pong":
            return False
        try:
            message = json.loads(text)
        except json.JSONDecodeError:
            self.malformed_count += 1
            logger.debug(
                "okx.ws_malformed_frame",
                extra={"fields": {"socket": self.name, "sample": text[:80]}},
            )
            return False
        if not isinstance(message, Mapping):
            self.malformed_count += 1
            return False
        event = message.get("event")
        if event == "error":
            logger.warning(
                "okx.ws_request_rejected",
                extra={
                    "fields": {
                        "socket": self.name,
                        "code": message.get("code"),
                        "msg": message.get("msg"),
                    }
                },
            )
            arg = message.get("arg")
            if isinstance(arg, Mapping):
                self.failed_subscriptions.add((str(arg.get("channel")), str(arg.get("instId"))))
            return False
        if event == "notice":
            logger.warning(
                "okx.ws_notice",
                extra={
                    "fields": {
                        "socket": self.name,
                        "code": message.get("code"),
                        "msg": message.get("msg"),
                    }
                },
            )
            return True  # e.g. 64008 service upgrade: reconnect proactively
        if event is not None:  # subscribe / unsubscribe acks
            return False
        if "arg" in message and "data" in message and self._on_message is not None:
            try:
                await self._on_message(message)
            except Exception:
                logger.exception("okx.ws_handler_failed")
        return False

    async def _backoff(self, attempt: int) -> None:
        delay = min(self._backoff_max, self._backoff_base * 2**attempt)
        delay *= 0.8 + random.random() * 0.4  # noqa: S311  (jitter, not crypto)
        await asyncio.sleep(delay)

    async def _set_state(self, state: str) -> None:
        if state == self.state:
            return
        self.state = state
        if self._on_state is not None:
            try:
                await self._on_state(state)
            except Exception:
                logger.exception("okx.ws_state_handler_failed")

    async def _notify_reconnected(self) -> None:
        if self._on_reconnected is not None:
            try:
                await self._on_reconnected()
            except Exception:
                logger.exception("okx.ws_reconnect_handler_failed")

    def _spawn(self, coro: Awaitable[None]) -> None:
        task: asyncio.Task[None] = asyncio.ensure_future(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
