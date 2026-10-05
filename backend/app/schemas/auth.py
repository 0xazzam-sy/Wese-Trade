from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.common import ApiModel
from app.schemas.user import UserPublic


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(ApiModel):
    user: UserPublic
    expires_at: datetime


class SessionResponse(ApiModel):
    """SPA bootstrap: always 200, so an anonymous visit does not log a console error."""

    authenticated: bool
    user: UserPublic | None


class SetupStatus(ApiModel):
    """First run: true only while the database has no user at all."""

    needs_setup: bool


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)
