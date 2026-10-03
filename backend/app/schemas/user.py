from __future__ import annotations

from datetime import datetime

from app.models.user import UserRole
from app.schemas.common import ApiModel


class UserPublic(ApiModel):
    id: int
    username: str
    role: UserRole
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
