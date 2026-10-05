from __future__ import annotations

from datetime import datetime

from pydantic import AnyHttpUrl

from app.schemas.common import ApiModel


class NewsItem(ApiModel):
    id: str
    title_ar: str
    source: str
    published_at: datetime  # UTC
    url: AnyHttpUrl
    original_language: str | None = None


class NewsFeed(ApiModel):
    items: list[NewsItem]
    available: bool
    message: str | None = None
    updated_at: datetime | None = None  # last successful refresh (UTC)
    stale: bool = False  # sources unreachable now; showing the last cached headlines
