"""Stable WebSocket event envelope shared by every realtime message.

{"type": "<event.type>", "timestamp": "<UTC ISO-8601>", "data": {...}}
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.utils.time import utc_now


class EventType(StrEnum):
    # --- Active in phase 1 ---------------------------------------------------
    SYSTEM_STATUS = "system.status"  # connection lifecycle / server status
    SYSTEM_HEARTBEAT = "system.heartbeat"  # periodic server -> client keepalive
    SYSTEM_PING = "system.ping"  # client -> server
    SYSTEM_PONG = "system.pong"  # server -> client reply to ping
    SYSTEM_ERROR = "system.error"  # protocol errors (bad message etc.)

    # --- Reserved for later phases (never emitted in phase 1) -----------------
    MARKET_TICK = "market.tick"
    MARKET_CANDLE = "market.candle"
    SIGNAL_LIVE = "signal.live"
    SIGNAL_CONFIRMED = "signal.confirmed"
    SCANNER_UPDATE = "scanner.update"


class EventEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str
    timestamp: datetime = Field(default_factory=utc_now)
    data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def of(cls, event_type: EventType, data: dict[str, Any] | None = None) -> EventEnvelope:
        return cls(type=event_type.value, data=data or {})

    def to_json(self) -> str:
        return self.model_dump_json()


class ClientMessage(BaseModel):
    """Inbound message from the browser. Same envelope shape; timestamp optional."""

    model_config = ConfigDict(extra="ignore")

    type: str = Field(max_length=64)
    data: dict[str, Any] = Field(default_factory=dict)


# WebSocket close codes (4000-4999 are application-defined).
CLOSE_UNAUTHORIZED = 4401
CLOSE_SESSION_EXPIRED = 4403
CLOSE_SERVER_SHUTDOWN = 1001
