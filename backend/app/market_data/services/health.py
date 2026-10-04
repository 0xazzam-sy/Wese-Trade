"""Market-data health: REST reachability, each realtime feed, streams and metadata."""

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
    provider: str = "okx"
    rest_reachable: bool | None = None  # None = not tried yet
    last_rest_success_at: datetime | None = None
    last_rest_error: str | None = None
    last_rest_error_at: datetime | None = None
    candle_feed_state: str = "disconnected"  # business socket (charts)
    quote_feed_state: str = "disconnected"  # public socket (prices, bid/ask, mark)
    last_candle_message_at: datetime | None = None
    last_quote_message_at: datetime | None = None
    reconnect_count: int = 0
    last_metadata_refresh_at: datetime | None = None
    symbol_count: int = 0
    rate_limited_count: int = 0
    gap_recoveries: int = 0
    gap_recovery_in_progress: bool = False
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
        """connected | connecting | reconnecting | degraded | disconnected.

        Charts depend on the candle feed, so its state dominates. "connected" only when the
        candle AND quote feeds are up, REST is reachable and no subscribed stream is stale.
        """
        if self.candle_feed_state != "connected":
            return self.candle_feed_state
        if (
            self.quote_feed_state != "connected"
            or self.rest_reachable is False
            or self.stale_streams
        ):
            return "degraded"
        return "connected"

    def snapshot(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "state": self.overall,
            "rest_reachable": self.rest_reachable,
            "last_rest_success_at": self.last_rest_success_at,
            "last_rest_error": self.last_rest_error,
            "last_rest_error_at": self.last_rest_error_at,
            "candle_feed_state": self.candle_feed_state,
            "quote_feed_state": self.quote_feed_state,
            "last_candle_message_at": self.last_candle_message_at,
            "last_quote_message_at": self.last_quote_message_at,
            "reconnect_count": self.reconnect_count,
            "last_metadata_refresh_at": self.last_metadata_refresh_at,
            "symbol_count": self.symbol_count,
            "rate_limited_count": self.rate_limited_count,
            "gap_recoveries": self.gap_recoveries,
            "gap_recovery_in_progress": self.gap_recovery_in_progress,
            "active_streams": sorted(self.active_streams),
            "stale_streams": sorted(self.stale_streams),
        }
