"""ORM models. Import every model here so Alembic autogenerate can discover it."""

from app.models.user import User, UserRole

__all__ = ["User", "UserRole"]
