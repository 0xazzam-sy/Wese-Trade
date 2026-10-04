"""Market data domain: normalized, exchange-agnostic types, provider contract and services.

The active provider is OKX public market data (`app.market_data.okx`). Exchange-specific code
is only reachable through the `MarketDataProvider` protocol, never from FastAPI routes.
"""
