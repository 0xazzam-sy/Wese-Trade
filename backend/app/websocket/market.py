"""App-WebSocket market subscription protocol.

Client -> server:
    {"type": "market.subscribe",   "data": {"symbol": "BTCUSDT", "timeframe": "5m"}}
    {"type": "market.unsubscribe", "data": {"symbol": "BTCUSDT", "timeframe": "5m"}}
Server -> client: `market.subscribed` ack, or `system.error` with a code.
"""

from __future__ import annotations

from app.analysis.service import AnalysisService
from app.core.logging import get_logger
from app.market_data.engine import MarketDataEngine
from app.market_data.exceptions import MarketDataError, SymbolUnavailable, UnknownSymbol
from app.market_data.timeframes import Timeframe
from app.websocket.events import ClientMessage, EventEnvelope, EventType
from app.websocket.manager import ClientConnection

MAX_SUBSCRIPTIONS_PER_CONNECTION = 8
logger = get_logger(__name__)


async def _error(connection: ClientConnection, code: str, data: dict[str, object]) -> None:
    await connection.send(EventEnvelope.of(EventType.SYSTEM_ERROR, {"code": code, **data}))


async def handle_market_message(
    connection: ClientConnection,
    market: MarketDataEngine | None,
    message: ClientMessage,
    analysis: AnalysisService | None = None,
) -> None:
    """A market subscription also subscribes the stream's analysis (`analysis.update`)."""
    symbol = message.data.get("symbol")
    timeframe_raw = message.data.get("timeframe")
    context: dict[str, object] = {"symbol": symbol, "timeframe": timeframe_raw}
    if market is None:
        await _error(connection, "market_data_disabled", context)
        return
    if not isinstance(symbol, str) or not isinstance(timeframe_raw, str) or len(symbol) > 32:
        await _error(connection, "invalid_market_request", context)
        return
    try:
        timeframe = Timeframe(timeframe_raw)
    except ValueError:
        await _error(connection, "invalid_timeframe", context)
        return

    if message.type == EventType.MARKET_UNSUBSCRIBE:
        if analysis is not None:
            await analysis.unsubscribe(connection.id, symbol, timeframe)
        await market.unsubscribe(connection.id, symbol, timeframe)
        return

    if len(market.subscriptions.keys_of(connection.id)) >= MAX_SUBSCRIPTIONS_PER_CONNECTION:
        await _error(connection, "too_many_subscriptions", context)
        return
    if not market.symbols.loaded:
        await _error(connection, "market_data_loading", context)
        return
    try:
        resolved = await market.subscribe(connection.id, symbol, timeframe)
    except UnknownSymbol:
        await _error(connection, "unknown_symbol", context)
        return
    except SymbolUnavailable:
        await _error(connection, "symbol_unavailable", context)
        return
    except MarketDataError:
        await _error(connection, "market_data_unavailable", context)
        return
    await connection.send(
        EventEnvelope.of(
            EventType.MARKET_SUBSCRIBED, {"symbol": resolved.symbol, "timeframe": timeframe.value}
        )
    )
    if analysis is not None:
        try:
            await analysis.subscribe(connection.id, resolved.symbol, timeframe)
        except Exception:  # analysis must never break the market subscription
            logger.exception("analysis.subscribe_failed")
