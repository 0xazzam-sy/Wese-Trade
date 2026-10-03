"""Market data domain: normalized, exchange-agnostic types and provider contracts.

Exchange-specific code (BingX) will live in `app.market_data.providers.bingx` and must
only be reached through the `MarketDataProvider` protocol — never from FastAPI routes.
"""
