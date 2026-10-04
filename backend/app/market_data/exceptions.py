"""Exchange-agnostic market-data errors. Routes translate these into HTTP responses."""

from __future__ import annotations


class MarketDataError(Exception):
    """Base class for provider errors."""


class ProviderUnavailable(MarketDataError):  # noqa: N818  (domain name, not "...Error")
    """Network failure, timeout or 5xx after retries."""


class ProviderRateLimited(MarketDataError):  # noqa: N818
    def __init__(self, retry_after: float) -> None:
        super().__init__(f"rate limited; retry after {retry_after:.1f}s")
        self.retry_after = retry_after


class InvalidProviderResponse(MarketDataError):  # noqa: N818
    """Response body did not match the expected schema."""


class ProviderApiError(MarketDataError):
    """The exchange returned an error code."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(f"provider error {code}: {message}")
        self.code = code
        self.message = message


class UnknownSymbol(MarketDataError):  # noqa: N818
    def __init__(self, symbol: str) -> None:
        super().__init__(f"unknown symbol: {symbol}")
        self.symbol = symbol


class SymbolUnavailable(MarketDataError):  # noqa: N818
    def __init__(self, symbol: str) -> None:
        super().__init__(f"symbol not available: {symbol}")
        self.symbol = symbol
