"""Tracks live WebSocket connections and fans out events.

Future market/signal publishers will call `broadcast()`; they never touch sockets directly.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket
from starlette.websockets import WebSocketState

from app.core.logging import get_logger
from app.websocket.events import EventEnvelope

logger = get_logger(__name__)


@dataclass(slots=True, eq=False)
class ClientConnection:
    websocket: WebSocket
    user_id: int
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, envelope: EventEnvelope) -> bool:
        if self.websocket.application_state is not WebSocketState.CONNECTED:
            return False
        async with self.send_lock:
            try:
                await self.websocket.send_text(envelope.to_json())
            except Exception:  # connection dropped mid-send
                return False
        return True


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: dict[str, ClientConnection] = {}

    @property
    def count(self) -> int:
        return len(self._connections)

    def register(self, websocket: WebSocket, user_id: int) -> ClientConnection:
        connection = ClientConnection(websocket=websocket, user_id=user_id)
        self._connections[connection.id] = connection
        logger.info(
            "ws.connected",
            extra={"fields": {"connection_id": connection.id, "clients": self.count}},
        )
        return connection

    def unregister(self, connection: ClientConnection) -> None:
        if self._connections.pop(connection.id, None) is not None:
            logger.info(
                "ws.disconnected",
                extra={"fields": {"connection_id": connection.id, "clients": self.count}},
            )

    async def broadcast(self, envelope: EventEnvelope) -> int:
        """Send to every client; returns the number of successful deliveries."""
        results = await asyncio.gather(
            *(c.send(envelope) for c in list(self._connections.values()))
        )
        return sum(results)

    async def close_all(self, code: int, reason: str = "") -> None:
        for connection in list(self._connections.values()):
            try:
                await connection.websocket.close(code=code, reason=reason)
            except Exception:  # already closed
                logger.debug("ws.close_failed", extra={"fields": {"id": connection.id}})
        self._connections.clear()
