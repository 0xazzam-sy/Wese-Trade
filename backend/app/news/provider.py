"""News provider contract. Concrete providers (and Arabic translation) arrive in a later phase."""

from __future__ import annotations

from typing import Protocol

from app.news.models import NewsItem


class NewsProvider(Protocol):
    name: str

    async def fetch_latest(self, *, limit: int) -> list[NewsItem]:
        """Return the latest items with Arabic headlines, newest first, timestamps in UTC."""
        ...
