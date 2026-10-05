"""User domain logic: creation and authentication. No HTTP concerns here."""

from __future__ import annotations

import re

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import (
    burn_verification_time,
    hash_password,
    needs_rehash,
    validate_password_strength,
    verify_password,
)
from app.models.user import User, UserRole
from app.utils.time import utc_now

USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")


class UserServiceError(Exception):
    """Base class for user-domain errors."""


class InvalidUsernameError(UserServiceError):
    pass


class WeakPasswordError(UserServiceError):
    def __init__(self, problems: list[str]) -> None:
        super().__init__(" ".join(problems))
        self.problems = problems


class UsernameTakenError(UserServiceError):
    pass


class LastAdminError(UserServiceError):
    """The change would leave no active administrator."""


def user_error_detail(exc: UserServiceError) -> str:
    """Stable API error codes (the UI maps them to Arabic messages)."""
    if isinstance(exc, InvalidUsernameError):
        return "invalid_username"
    if isinstance(exc, WeakPasswordError):
        return "weak_password"
    if isinstance(exc, UsernameTakenError):
        return "username_taken"
    if isinstance(exc, LastAdminError):
        return "last_admin"
    return "invalid_user"


def normalize_username(username: str) -> str:
    return username.strip().lower()


async def count_users(session: AsyncSession) -> int:
    return int(await session.scalar(select(func.count()).select_from(User)) or 0)


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    return await session.scalar(select(User).where(User.username == normalize_username(username)))


async def create_user(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    role: UserRole,
    is_active: bool = True,
) -> User:
    normalized = normalize_username(username)
    if not USERNAME_PATTERN.fullmatch(normalized):
        raise InvalidUsernameError(
            "Username must be 3-64 characters: letters, digits, '_', '.', '-'."
        )
    if problems := validate_password_strength(password):
        raise WeakPasswordError(problems)

    user = User(
        username=normalized,
        password_hash=hash_password(password),
        role=role,
        is_active=is_active,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise UsernameTakenError(f"Username '{normalized}' already exists.") from exc
    await session.refresh(user)
    return user


async def authenticate(session: AsyncSession, *, username: str, password: str) -> User | None:
    """Return the user if credentials are valid and the account is active, else None.

    Timing is equalized for unknown usernames to avoid user enumeration.
    """
    user = await get_user_by_username(session, username)
    if user is None:
        burn_verification_time(password)
        return None
    if not verify_password(password, user.password_hash):
        return None
    if not user.is_active:
        return None

    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = utc_now()
    await session.commit()
    await session.refresh(user)
    return user


async def list_users(session: AsyncSession) -> list[User]:
    return list((await session.scalars(select(User).order_by(User.id))).all())


async def update_user(
    session: AsyncSession, user: User, *, role: UserRole | None, is_active: bool | None
) -> User:
    new_role = role if role is not None else user.role
    new_active = is_active if is_active is not None else user.is_active
    if (
        user.role is UserRole.ADMIN
        and user.is_active
        and (new_role is not UserRole.ADMIN or not new_active)
    ):
        others = await session.scalar(
            select(func.count())
            .select_from(User)
            .where(User.role == UserRole.ADMIN, User.is_active.is_(True), User.id != user.id)
        )
        if not others:
            raise LastAdminError("At least one active administrator is required.")
    user.role = new_role
    user.is_active = new_active
    await session.commit()
    await session.refresh(user)
    return user


async def set_password(session: AsyncSession, user: User, password: str) -> User:
    if problems := validate_password_strength(password):
        raise WeakPasswordError(problems)
    user.password_hash = hash_password(password)
    await session.commit()
    await session.refresh(user)
    return user
