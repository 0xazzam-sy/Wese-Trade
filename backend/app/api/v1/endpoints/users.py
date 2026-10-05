"""User management (administrators only). No terminal needed for normal product use."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import SessionDep, require_roles
from app.models.user import User, UserRole
from app.schemas.user import PasswordReset, UserCreate, UserPublic, UserUpdate
from app.services.user_service import (
    UserServiceError,
    create_user,
    get_user_by_id,
    list_users,
    set_password,
    update_user,
    user_error_detail,
)

router = APIRouter(
    prefix="/users", tags=["users"], dependencies=[Depends(require_roles(UserRole.ADMIN))]
)


async def _user(session: SessionDep, user_id: int) -> User:
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user_not_found")
    return user


def _invalid(exc: UserServiceError) -> HTTPException:
    code = user_error_detail(exc)
    return HTTPException(
        status.HTTP_409_CONFLICT
        if code == "username_taken"
        else status.HTTP_422_UNPROCESSABLE_CONTENT,
        code,
    )


@router.get("")
async def users(session: SessionDep) -> dict[str, Any]:
    return {"items": [UserPublic.model_validate(u) for u in await list_users(session)]}


@router.post("", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def add_user(payload: UserCreate, session: SessionDep) -> UserPublic:
    try:
        user = await create_user(
            session, username=payload.username, password=payload.password, role=payload.role
        )
    except UserServiceError as exc:
        raise _invalid(exc) from exc
    return UserPublic.model_validate(user)


@router.patch("/{user_id}", response_model=UserPublic)
async def change_user(user_id: int, payload: UserUpdate, session: SessionDep) -> UserPublic:
    user = await _user(session, user_id)
    try:
        user = await update_user(session, user, role=payload.role, is_active=payload.is_active)
    except UserServiceError as exc:
        raise _invalid(exc) from exc
    return UserPublic.model_validate(user)


@router.post("/{user_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(user_id: int, payload: PasswordReset, session: SessionDep) -> None:
    user = await _user(session, user_id)
    try:
        await set_password(session, user, payload.password)
    except UserServiceError as exc:
        raise _invalid(exc) from exc
