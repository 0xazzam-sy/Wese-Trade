"""Builds the market data engine from settings (the only place the exchange is chosen)."""

from __future__ import annotations

from app.core.config import Settings
from app.market_data.engine import MarketDataEngine, Publisher
from app.market_data.okx.provider import OkxProvider
from app.market_data.okx.rest import OkxRestClient
from app.market_data.okx.stream import OkxSocket
from app.market_data.services.health import MarketHealth


def build_market_engine(settings: Settings, publisher: Publisher) -> MarketDataEngine:
    health = MarketHealth(provider="okx")
    rest = OkxRestClient(settings.okx_rest_url, on_result=health.record_rest)
    public = OkxSocket("public", settings.okx_public_ws_url)
    business = OkxSocket("business", settings.okx_business_ws_url)
    provider = OkxProvider(rest, public, business)
    return MarketDataEngine(
        provider, publisher, health=health, stale_after=settings.market_stale_after_seconds
    )
