from __future__ import annotations

from app.core.config import Settings
from app.news.models import NewsFeed

__all__ = ["NewsFeed", "get_news_feed"]


async def get_news_feed(settings: Settings) -> NewsFeed:
    # No provider is implemented in phase 1. Return an honest empty feed (never fake items).
    del settings
    return NewsFeed(items=[], available=False, message="news_provider_not_configured")
