"""Live microstructure feed against the real OKX public WebSocket (no credentials)."""

from __future__ import annotations

import asyncio

import pytest

from app.core.config import get_settings
from app.execution.micro import MicroFeed

pytestmark = pytest.mark.live


async def test_live_books5_and_trades_reach_ok_health() -> None:
    feed = MicroFeed(get_settings().okx_public_ws_url)
    feed.acquire("BTCUSDT")
    try:
        for _ in range(60):
            await asyncio.sleep(0.5)
            snap = feed.snapshot("BTCUSDT")
            if snap.status == "ok" and snap.flow_imbalance is not None:
                break
        assert snap.status == "ok", snap
        assert snap.spread_bp is not None and 0 < snap.spread_bp < 50
        assert snap.book_imbalance is not None and -1 <= snap.book_imbalance <= 1
        assert feed.messages > 0
    finally:
        await feed.close()
