"""Internal backend -> frontend WebSocket endpoint: `/api/v1/ws`.

Lifecycle: origin check -> cookie auth -> `system.status` -> heartbeat loop + receive loop.
"""

from __future__ import annotations

import asyncio
import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.api.deps import resolve_user_from_token
from app.auth.tokens import ACCESS_COOKIE_NAME, InvalidTokenError, decode_access_token
from app.core.logging import get_logger
from app.core.state import AppResources
from app.market_data.engine import MarketDataEngine
from app.utils.time import utc_now
from app.websocket.events import (
    CLOSE_SESSION_EXPIRED,
    CLOSE_UNAUTHORIZED,
    ClientMessage,
    EventEnvelope,
    EventType,
)
from app.websocket.manager import ClientConnection
from app.websocket.market import handle_market_message

router = APIRouter(tags=["realtime"])
logger = get_logger(__name__)

MAX_CLIENT_MESSAGE_BYTES = 4096


def _origin_allowed(websocket: WebSocket, allowed: list[str]) -> bool:
    origin = websocket.headers.get("origin")
    # Non-browser clients send no Origin; they still need a valid auth cookie.
    return origin is None or origin.rstrip("/") in allowed


async def _heartbeat(connection: ClientConnection, interval: float, expires_at: float) -> None:
    while True:
        await asyncio.sleep(interval)
        if utc_now().timestamp() >= expires_at:
            await connection.websocket.close(code=CLOSE_SESSION_EXPIRED, reason="session_expired")
            return
        if not await connection.send(EventEnvelope.of(EventType.SYSTEM_HEARTBEAT)):
            return


async def _handle_message(
    connection: ClientConnection, market: MarketDataEngine | None, raw: str
) -> None:
    if len(raw.encode()) > MAX_CLIENT_MESSAGE_BYTES:
        await connection.send(
            EventEnvelope.of(EventType.SYSTEM_ERROR, {"code": "message_too_large"})
        )
        return
    try:
        message = ClientMessage.model_validate_json(raw)
    except ValidationError:
        await connection.send(EventEnvelope.of(EventType.SYSTEM_ERROR, {"code": "invalid_message"}))
        return

    if message.type == EventType.SYSTEM_PING:
        await connection.send(EventEnvelope.of(EventType.SYSTEM_PONG, {"echo": message.data}))
    elif message.type in (EventType.MARKET_SUBSCRIBE, EventType.MARKET_UNSUBSCRIBE):
        await handle_market_message(connection, market, message)
    else:
        await connection.send(
            EventEnvelope.of(
                EventType.SYSTEM_ERROR, {"code": "unsupported_type", "type": message.type}
            )
        )


@router.websocket("/ws")
async def realtime(websocket: WebSocket) -> None:
    resources: AppResources = websocket.app.state.resources
    settings = resources.settings

    if not _origin_allowed(websocket, settings.frontend_origin):
        logger.warning(
            "ws.origin_rejected", extra={"fields": {"origin": websocket.headers.get("origin")}}
        )
        await websocket.close(code=CLOSE_UNAUTHORIZED)  # rejected before accept -> HTTP 403
        return

    token = websocket.cookies.get(ACCESS_COOKIE_NAME)
    async with resources.database.session_factory() as session:
        user = await resolve_user_from_token(session, token, settings)

    await websocket.accept()
    if user is None or token is None:
        # Accept-then-close so the browser receives a meaningful close code.
        await websocket.close(code=CLOSE_UNAUTHORIZED, reason="unauthorized")
        return
    try:
        expires_at = decode_access_token(token, secret_key=settings.secret_key).expires_at
    except InvalidTokenError:
        await websocket.close(code=CLOSE_UNAUTHORIZED, reason="unauthorized")
        return

    connection = resources.connections.register(websocket, user.id)
    heartbeat = asyncio.create_task(
        _heartbeat(connection, settings.ws_heartbeat_seconds, expires_at.timestamp())
    )
    try:
        await connection.send(
            EventEnvelope.of(
                EventType.SYSTEM_STATUS,
                {
                    "state": "connected",
                    "connection_id": connection.id,
                    "heartbeat_interval_seconds": settings.ws_heartbeat_seconds,
                    "server_time": utc_now().isoformat(),
                },
            )
        )
        if resources.market is not None:
            await connection.send(resources.market.status_event())
        while True:
            raw = await websocket.receive_text()
            await _handle_message(connection, resources.market, raw)
    except WebSocketDisconnect:
        pass
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        if resources.market is not None:
            await resources.market.release_all(connection.id)
        await resources.connections.unregister(connection)
