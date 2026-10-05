"""Shared FastAPI dependencies."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.tokens import ACCESS_COOKIE_NAME, InvalidTokenError, decode_access_token
from app.core.config import Settings
from app.core.state import AppResources
from app.models.user import User, UserRole
from app.services.user_service import get_user_by_id


def get_resources(request: Request) -> AppResources:
    resources: AppResources = request.app.state.resources
    return resources


def get_settings_dep(resources: Annotated[AppResources, Depends(get_resources)]) -> Settings:
    return resources.settings


async def get_session(
    resources: Annotated[AppResources, Depends(get_resources)],
) -> AsyncIterator[AsyncSession]:
    async with resources.database.session_factory() as session:
        yield session


Resources = Annotated[AppResources, Depends(get_resources)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="not_authenticated",
)


async def resolve_user_from_token(
    session: AsyncSession, token: str | None, settings: Settings
) -> User | None:
    """Shared by HTTP and WebSocket authentication."""
    if not token:
        return None
    try:
        claims = decode_access_token(token, secret_key=settings.signing_key)
    except InvalidTokenError:
        return None
    user = await get_user_by_id(session, claims.user_id)
    if user is None or not user.is_active:
        return None
    return user


async def get_optional_user(
    request: Request, session: SessionDep, settings: SettingsDep
) -> User | None:
    return await resolve_user_from_token(session, request.cookies.get(ACCESS_COOKIE_NAME), settings)


async def get_current_user(user: Annotated[User | None, Depends(get_optional_user)]) -> User:
    if user is None:
        raise _UNAUTHORIZED
    return user


OptionalUser = Annotated[User | None, Depends(get_optional_user)]
CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole) -> Callable[[User], Coroutine[Any, Any, User]]:
    """Dependency factory: `Depends(require_roles(UserRole.ADMIN))`."""
    allowed = frozenset(roles)

    async def _checker(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        return user

    return _checker
