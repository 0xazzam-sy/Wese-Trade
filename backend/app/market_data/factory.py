"""Builds the market data engine from settings (the only place BingX is chosen)."""

from __future__ import annotations

from app.core.config import Settings
from app.market_data.bingx.provider import BingXProvider
from app.market_data.bingx.rest import BingXRestClient
from app.market_data.bingx.stream import BingXMarketStream
from app.market_data.engine import MarketDataEngine, Publisher
from app.market_data.services.health import MarketHealth


def build_market_engine(settings: Settings, publisher: Publisher) -> MarketDataEngine:
    health = MarketHealth(provider="bingx")
    rest = BingXRestClient(settings.bingx_base_url, on_result=health.record_rest)
    stream = BingXMarketStream(settings.bingx_ws_url)
    provider = BingXProvider(rest, stream)
    return MarketDataEngine(
        provider, publisher, health=health, stale_after=settings.market_stale_after_seconds
    )
