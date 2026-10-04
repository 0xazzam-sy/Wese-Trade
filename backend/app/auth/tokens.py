"""Signed access tokens (JWT, HS256), delivered to the SPA in an httpOnly cookie."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from app.utils.time import utc_now

ALGORITHM = "HS256"
TOKEN_AUDIENCE = "wese-trade-web"  # noqa: S105  (audience claim, not a secret)
ACCESS_COOKIE_NAME = "ns_access"


@dataclass(frozen=True, slots=True)
class IssuedToken:
    token: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class TokenClaims:
    user_id: int
    expires_at: datetime


class InvalidTokenError(Exception):
    """Raised when a token is missing, malformed, expired or tampered with."""


def create_access_token(*, user_id: int, secret_key: str, expire_minutes: int) -> IssuedToken:
    now = utc_now()
    expires_at = now + timedelta(minutes=expire_minutes)
    payload = {
        "sub": str(user_id),
        "aud": TOKEN_AUDIENCE,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "typ": "access",
    }
    return IssuedToken(jwt.encode(payload, secret_key, algorithm=ALGORITHM), expires_at)


def decode_access_token(token: str, *, secret_key: str) -> TokenClaims:
    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=[ALGORITHM],
            audience=TOKEN_AUDIENCE,
            options={"require": ["sub", "exp", "iat", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    if payload.get("typ") != "access":
        raise InvalidTokenError("unexpected token type")
    try:
        user_id = int(payload["sub"])
    except (TypeError, ValueError) as exc:
        raise InvalidTokenError("invalid subject") from exc
    return TokenClaims(user_id=user_id, expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC))
