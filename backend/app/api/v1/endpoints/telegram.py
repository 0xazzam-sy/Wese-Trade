"""Telegram administration (v1.2, admin only). The bot token is write-only: responses only
ever contain a masked hint; it is never logged."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.api.deps import Resources, require_roles
from app.models.user import UserRole
from app.telegram.client import TelegramError
from app.telegram.service import TelegramConfigError, TelegramService

router = APIRouter(
    prefix="/telegram", tags=["telegram"], dependencies=[Depends(require_roles(UserRole.ADMIN))]
)


def _service(resources: Resources) -> TelegramService:
    if resources.telegram is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="telegram_unavailable")
    return resources.telegram


Service = Annotated[TelegramService, Depends(_service)]


class TokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=128)


class OptionsIn(BaseModel):
    enabled: bool | None = None
    events: dict[str, bool] | None = None


class RecipientIn(BaseModel):
    name: str | None = Field(default=None, max_length=64)
    chat_id: str | None = Field(default=None, max_length=64)
    enabled: bool | None = None
    buy: bool | None = None
    sell: bool | None = None
    timeframes: list[str] | None = None
    symbols: list[str] | None = None
    lifecycle: bool | None = None


class FixtureIn(BaseModel):
    side: str = Field(pattern="^(BUY|SELL)$")
    recipient_id: int | None = None


def _bad(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("")
async def settings(service: Service) -> dict[str, Any]:
    return {**service.public(), "health": await service.health()}


@router.put("/token")
async def set_token(body: TokenIn, service: Service) -> dict[str, Any]:
    try:
        return await service.set_token(body.token)
    except TelegramConfigError as exc:
        raise _bad(exc) from None


@router.delete("/token")
async def clear_token(service: Service) -> dict[str, Any]:
    return await service.clear_token()


@router.post("/test-connection")
async def check_connection(service: Service) -> dict[str, Any]:
    return await service.test_connection()


@router.patch("/options")
async def options(body: OptionsIn, service: Service) -> dict[str, Any]:
    return await service.set_options(enabled=body.enabled, events=body.events)


@router.post("/test-message")
async def send_test_message(
    service: Service, recipient_id: int | None = Query(default=None)
) -> list[dict[str, Any]]:
    try:
        return await service.send_test_message(recipient_id)
    except (TelegramConfigError, TelegramError) as exc:
        raise _bad(exc) from None


@router.post("/test-signal")
async def send_test_signal(body: FixtureIn, service: Service) -> dict[str, Any]:
    """A clearly marked TEST BUY / SELL through the real pipeline (dedupe + delivery log)."""
    try:
        ids = await service.send_fixture(1 if body.side == "BUY" else -1, body.recipient_id)
    except (TelegramConfigError, TelegramError) as exc:
        raise _bad(exc) from None
    await service.drain()
    return {"deliveries": ids, "log": await service.deliveries(limit=max(5, len(ids)))}


@router.get("/chats")
async def chats(service: Service) -> list[dict[str, Any]]:
    try:
        return await service.chat_candidates()
    except (TelegramConfigError, TelegramError) as exc:
        raise _bad(exc) from None


@router.post("/recipients", status_code=status.HTTP_201_CREATED)
async def add_recipient(body: RecipientIn, service: Service) -> dict[str, Any]:
    try:
        return await service.add_recipient(body.model_dump(exclude_none=True))
    except TelegramConfigError as exc:
        raise _bad(exc) from None


@router.patch("/recipients/{rid}")
async def update_recipient(rid: int, body: RecipientIn, service: Service) -> dict[str, Any]:
    try:
        return await service.update_recipient(rid, body.model_dump(exclude_none=True))
    except TelegramConfigError as exc:
        raise _bad(exc) from None


@router.delete("/recipients/{rid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_recipient(rid: int, service: Service) -> None:
    try:
        await service.delete_recipient(rid)
    except TelegramConfigError as exc:
        raise _bad(exc) from None


@router.get("/deliveries")
async def deliveries(
    service: Service, limit: int = Query(50, ge=1, le=500)
) -> list[dict[str, Any]]:
    return await service.deliveries(limit)
