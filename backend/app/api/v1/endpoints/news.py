"""News routes. Phase 1: no provider configured, so the feed is honestly empty.

News is display-only and MUST NEVER feed into the signal engine.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentUser, Resources
from app.news.service import NewsFeed, get_news_feed

router = APIRouter(prefix="/news", tags=["news"])


@router.get("", response_model=NewsFeed)
async def list_news(_: CurrentUser, resources: Resources) -> NewsFeed:
    return await get_news_feed(resources.settings)
