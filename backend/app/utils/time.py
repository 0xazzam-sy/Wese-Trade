"""Time helpers. All internal timestamps are timezone-aware UTC."""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Treat naive datetimes as UTC (e.g. values read back from SQLite)."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def utc_isoformat(value: datetime) -> str:
    return ensure_utc(value).isoformat().replace("+00:00", "Z")
