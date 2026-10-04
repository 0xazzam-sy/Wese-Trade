"""BingX public-market WebSocket client (one shared connection for the whole app).

Responsibilities:
- connect / reconnect with exponential backoff + jitter, clean shutdown
- subscription registry: idempotent subscribe/unsubscribe, full resubscribe after reconnect
- gzip frame decoding, Ping -> Pong heartbeat, silence watchdog (dead-socket detection)
- tolerate malformed frames (logged at DEBUG, counted) without killing the loop
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import random
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from app.core.logging import get_logger
from app.market_data.bingx.constants import (
    WS_BACKOFF_BASE_SECONDS,
    WS_BACKOFF_MAX_SECONDS,
    WS_OPEN_TIMEOUT_SECONDS,
    WS_SILENCE_TIMEOUT_SECONDS,
)
from app.market_data.bingx.exceptions import BingXInvalidResponse
from app.market_data.bingx.parser import decode_frame, parse_json

logger = get_logger(__name__)


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

    # BingX uses an application-level "Ping"/"Pong" text heartbeat, so protocol pings are off.
    connection = await connect(
        url,
        open_timeout=WS_OPEN_TIMEOUT_SECONDS,
        ping_interval=None,
        max_size=2**22,
        close_timeout=5,
    )
    return connection


class BingXMarketStream:
    def __init__(
        self,
        url: str,
        *,
        connector: Connector = default_connector,
        silence_timeout: float = WS_SILENCE_TIMEOUT_SECONDS,
        backoff_base: float = WS_BACKOFF_BASE_SECONDS,
        backoff_max: float = WS_BACKOFF_MAX_SECONDS,
    ) -> None:
        self._url = url
        self._connector = connector
        self._silence_timeout = silence_timeout
        self._backoff_base = backoff_base
        self._backoff_max = backoff_max
        self._subscriptions: set[str] = set()
        self._socket: WebSocketLike | None = None
        self._task: asyncio.Task[None] | None = None
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
        self.failed_subscriptions: set[str] = set()

    # --- wiring -------------------------------------------------------------
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
    def subscriptions(self) -> frozenset[str]:
        return frozenset(self._subscriptions)

    # --- lifecycle ----------------------------------------------------------
    def start(self) -> None:
        if self._task is None:
            self._closing = False
            self._task = asyncio.create_task(self._run(), name="bingx-market-stream")

    async def close(self) -> None:
        self._closing = True
        socket = self._socket
        if socket is not None:
            with contextlib.suppress(Exception):
                await socket.close()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        for task in list(self._background):
            task.cancel()
        await self._set_state("disconnected")

    # --- subscriptions ------------------------------------------------------
    async def subscribe(self, data_type: str) -> None:
        if data_type in self._subscriptions:
            return
        self._subscriptions.add(data_type)
        self.failed_subscriptions.discard(data_type)
        await self._send_request("sub", data_type)

    async def unsubscribe(self, data_type: str) -> None:
        if data_type not in self._subscriptions:
            return
        self._subscriptions.discard(data_type)
        await self._send_request("unsub", data_type)

    async def _send_request(self, req_type: str, data_type: str) -> None:
        if self._socket is None or self.state != "connected":
            return  # (re)subscribed on the next successful connect
        message = {"id": uuid.uuid4().hex, "reqType": req_type, "dataType": data_type}
        await self._send(json.dumps(message))

    async def _send(self, text: str) -> None:
        socket = self._socket
        if socket is None:
            return
        async with self._send_lock:
            try:
                await socket.send(text)
            except Exception as exc:  # socket died; the read loop will reconnect
                logger.debug("bingx.ws_send_failed", extra={"fields": {"error": str(exc)}})

    # --- main loop ----------------------------------------------------------
    async def _run(self) -> None:
        attempt = 0
        has_connected = False
        while not self._closing:
            await self._set_state("reconnecting" if has_connected else "connecting")
            try:
                self._socket = await self._connector(self._url)
            except Exception as exc:
                logger.warning("bingx.ws_connect_failed", extra={"fields": {"error": str(exc)}})
                await self._backoff(attempt)
                attempt += 1
                continue

            attempt = 0
            self.last_message_monotonic = time.monotonic()
            await self._set_state("connected")
            logger.info(
                "bingx.ws_connected",
                extra={
                    "fields": {
                        "reconnects": self.reconnect_count,
                        "streams": len(self._subscriptions),
                    }
                },
            )
            for data_type in sorted(self._subscriptions):
                await self._send_request("sub", data_type)
            if has_connected:
                logger.info(
                    "bingx.ws_resubscribed", extra={"fields": {"streams": len(self._subscriptions)}}
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
            logger.warning("bingx.ws_disconnected", extra={"fields": {"reason": reason}})
            await self._set_state("reconnecting")
            await self._backoff(0)

    async def _read_loop(self) -> str:
        socket = self._socket
        if socket is None:
            return "no_socket"
        while not self._closing:
            try:
                frame = await asyncio.wait_for(socket.recv(), timeout=self._silence_timeout)
            except TimeoutError:
                return "silence_timeout"
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return f"closed: {type(exc).__name__}"
            self.last_message_monotonic = time.monotonic()
            await self._handle_frame(frame)
        return "closing"

    async def _handle_frame(self, frame: str | bytes) -> None:
        text = decode_frame(frame).strip()
        if text == "Ping":
            await self._send("Pong")
            return
        try:
            message = parse_json(text)
        except BingXInvalidResponse:
            self.malformed_count += 1
            logger.debug("bingx.ws_malformed_frame", extra={"fields": {"sample": text[:80]}})
            return
        if not isinstance(message, Mapping):
            self.malformed_count += 1
            return
        if "ping" in message:  # alternate JSON heartbeat form
            await self._send(json.dumps({"pong": message["ping"], "time": message.get("time")}))
            return
        if "dataType" in message and "data" in message:
            if self._on_message is not None:
                try:
                    await self._on_message(message)
                except Exception:
                    logger.exception("bingx.ws_handler_failed")
            return
        if "id" in message and message.get("code") not in (0, None):
            logger.warning(
                "bingx.ws_request_rejected",
                extra={"fields": {"code": message.get("code"), "msg": message.get("msg")}},
            )
            data_type = message.get("dataType")
            if isinstance(data_type, str):
                self.failed_subscriptions.add(data_type)

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
                logger.exception("bingx.ws_state_handler_failed")

    async def _notify_reconnected(self) -> None:
        if self._on_reconnected is not None:
            try:
                await self._on_reconnected()
            except Exception:
                logger.exception("bingx.ws_reconnect_handler_failed")

    def _spawn(self, coro: Awaitable[None]) -> None:
        task: asyncio.Task[None] = asyncio.ensure_future(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)
