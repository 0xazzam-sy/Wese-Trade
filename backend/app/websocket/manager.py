"""Tracks live WebSocket connections and fans out events.

Each connection has a bounded outbound queue drained by its own writer task, so producers
(the market data engine) never await a slow browser. A client that falls too far behind is
disconnected (it reconnects and resyncs) instead of growing memory without bound.
Implements the market engine's `Publisher` protocol (`send_to` / `broadcast`).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.core.logging import get_logger
from app.websocket.events import EventEnvelope

logger = get_logger(__name__)

OUTBOX_LIMIT = 2000
CLOSE_TRY_AGAIN_LATER = 1013


@dataclass(slots=True, eq=False)
class ClientConnection:
    websocket: WebSocket
    user_id: int
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    outbox: asyncio.Queue[EventEnvelope | None] = field(
        default_factory=lambda: asyncio.Queue(maxsize=OUTBOX_LIMIT)
    )
    writer: asyncio.Task[None] | None = None
    closer: asyncio.Task[None] | None = None
    overflowed: bool = False

    def enqueue(self, envelope: EventEnvelope) -> bool:
        if self.overflowed or self.websocket.application_state is not WebSocketState.CONNECTED:
            return False
        try:
            self.outbox.put_nowait(envelope)
        except asyncio.QueueFull:
            self.overflowed = True
            logger.warning("ws.client_too_slow", extra={"fields": {"connection_id": self.id}})
            self.closer = asyncio.ensure_future(self._close_slow())
            return False
        return True

    async def send(self, envelope: EventEnvelope) -> bool:
        return self.enqueue(envelope)

    async def _close_slow(self) -> None:
        with contextlib.suppress(Exception):
            await self.websocket.close(code=CLOSE_TRY_AGAIN_LATER, reason="client_too_slow")

    async def run_writer(self) -> None:
        while True:
            envelope = await self.outbox.get()
            if envelope is None:
                return
            try:
                await self.websocket.send_text(envelope.to_json())
            except Exception:  # connection dropped mid-send
                return

    def start(self) -> None:
        self.writer = asyncio.create_task(self.run_writer(), name=f"ws-writer-{self.id}")

    async def stop(self) -> None:
        if self.writer is None:
            return
        with contextlib.suppress(asyncio.QueueFull):
            self.outbox.put_nowait(None)  # flush what is queued, then exit
        try:
            await asyncio.wait_for(self.writer, timeout=2)
        except (TimeoutError, asyncio.CancelledError):
            self.writer.cancel()


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, ClientConnection] = {}

    @property
    def count(self) -> int:
        return len(self._connections)

    def register(self, websocket: WebSocket, user_id: int) -> ClientConnection:
        connection = ClientConnection(websocket=websocket, user_id=user_id)
        connection.start()
        self._connections[connection.id] = connection
        logger.info(
            "ws.connected",
            extra={"fields": {"connection_id": connection.id, "clients": self.count}},
        )
        return connection

    async def unregister(self, connection: ClientConnection) -> None:
        if self._connections.pop(connection.id, None) is not None:
            logger.info(
                "ws.disconnected",
                extra={"fields": {"connection_id": connection.id, "clients": self.count}},
            )
        await connection.stop()

    def send_to(self, consumers: Iterable[str], envelope: EventEnvelope) -> None:
        for consumer in consumers:
            connection = self._connections.get(consumer)
            if connection is not None:
                connection.enqueue(envelope)

    def broadcast(self, envelope: EventEnvelope) -> None:
        for connection in list(self._connections.values()):
            connection.enqueue(envelope)

    async def close_all(self, code: int, reason: str = "") -> None:
        for connection in list(self._connections.values()):
            try:
                await connection.websocket.close(code=code, reason=reason)
            except Exception:  # already closed
                logger.debug("ws.close_failed", extra={"fields": {"id": connection.id}})
            await connection.stop()
        self._connections.clear()
