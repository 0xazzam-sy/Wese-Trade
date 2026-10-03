from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password, verify_password
from app.models.user import User, UserRole
from app.services.user_service import (
    InvalidUsernameError,
    UsernameTakenError,
    WeakPasswordError,
    authenticate,
    count_users,
    create_user,
)
from tests.conftest import ADMIN_PASSWORD


def test_password_hash_is_argon2_and_verifies() -> None:
    hashed = hash_password("a-sufficiently-long-password")
    assert hashed.startswith("$argon2id$")
    assert "a-sufficiently-long-password" not in hashed
    assert verify_password("a-sufficiently-long-password", hashed) is True
    assert verify_password("wrong-password-value", hashed) is False
    assert verify_password("anything", "not-a-valid-hash") is False


def test_same_password_hashes_differently() -> None:
    assert hash_password("same-password-twice") != hash_password("same-password-twice")


async def test_create_user_persists_hashed_password(session: AsyncSession) -> None:
    user = await create_user(
        session, username="  Analyst.One ", password="Analyst-Password-1", role=UserRole.ANALYST
    )
    assert user.id is not None
    assert user.username == "analyst.one"
    assert user.role is UserRole.ANALYST
    assert user.is_active is True
    assert user.password_hash != "Analyst-Password-1"
    assert user.created_at.tzinfo is not None
    assert user.last_login_at is None
    assert await count_users(session) == 1


async def test_duplicate_username_rejected(session: AsyncSession, admin_user: User) -> None:
    with pytest.raises(UsernameTakenError):
        await create_user(session, username="ADMIN", password=ADMIN_PASSWORD, role=UserRole.VIEWER)


async def test_weak_password_rejected(session: AsyncSession) -> None:
    with pytest.raises(WeakPasswordError):
        await create_user(session, username="viewer", password="short", role=UserRole.VIEWER)


async def test_invalid_username_rejected(session: AsyncSession) -> None:
    with pytest.raises(InvalidUsernameError):
        await create_user(session, username="a b", password=ADMIN_PASSWORD, role=UserRole.VIEWER)


async def test_authenticate_updates_last_login(session: AsyncSession, admin_user: User) -> None:
    user = await authenticate(session, username="admin", password=ADMIN_PASSWORD)
    assert user is not None
    assert user.last_login_at is not None
    assert user.last_login_at.tzinfo is not None


async def test_authenticate_rejects_inactive_user(session: AsyncSession, admin_user: User) -> None:
    admin_user.is_active = False
    await session.commit()
    assert await authenticate(session, username="admin", password=ADMIN_PASSWORD) is None
