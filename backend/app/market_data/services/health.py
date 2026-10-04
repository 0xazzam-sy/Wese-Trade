"""Market-data health tracking (REST reachability, exchange WS, streams, metadata)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.logging import get_logger
from app.utils.time import utc_now

logger = get_logger(__name__)


@dataclass
class MarketHealth:
    provider: str = "bingx"
    rest_reachable: bool | None = None  # None = not tried yet
    last_rest_success_at: datetime | None = None
    last_rest_error: str | None = None
    last_rest_error_at: datetime | None = None
    ws_state: str = "disconnected"
    last_ws_message_at: datetime | None = None
    reconnect_count: int = 0
    last_metadata_refresh_at: datetime | None = None
    symbol_count: int = 0
    rate_limited_count: int = 0
    gap_recoveries: int = 0
    active_streams: list[str] = field(default_factory=list)
    stale_streams: list[str] = field(default_factory=list)
    # Called after anything that may change `overall` (set by the engine to broadcast).
    on_change: Callable[[], None] | None = field(default=None, repr=False)

    def record_rest(self, ok: bool, error: str | None) -> None:
        now = utc_now()
        if ok:
            self.last_rest_success_at = now
            if self.rest_reachable is not True:
                logger.info("market.rest_available")
                self.rest_reachable = True
                self._changed()
            return
        if error == "rate_limited":
            self.rate_limited_count += 1
            return  # throttling is not unavailability
        self.last_rest_error = error
        self.last_rest_error_at = now
        if self.rest_reachable is not False:
            logger.warning("market.rest_unavailable", extra={"fields": {"error": error}})
            self.rest_reachable = False
            self._changed()

    def _changed(self) -> None:
        if self.on_change is not None:
            self.on_change()

    @property
    def overall(self) -> str:
        """connected | connecting | reconnecting | degraded | disconnected."""
        if self.ws_state == "connected":
            if self.rest_reachable is False or self.stale_streams:
                return "degraded"
            return "connected"
        return self.ws_state

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "state": self.overall,
            "rest_reachable": self.rest_reachable,
            "last_rest_success_at": self.last_rest_success_at,
            "last_rest_error": self.last_rest_error,
            "last_rest_error_at": self.last_rest_error_at,
            "ws_state": self.ws_state,
            "last_ws_message_at": self.last_ws_message_at,
            "reconnect_count": self.reconnect_count,
            "last_metadata_refresh_at": self.last_metadata_refresh_at,
            "symbol_count": self.symbol_count,
            "rate_limited_count": self.rate_limited_count,
            "gap_recoveries": self.gap_recoveries,
            "active_streams": sorted(self.active_streams),
            "stale_streams": sorted(self.stale_streams),
        }
