"""News routes: real Arabic headlines from configured RSS/Atom feeds (display only).

News MUST NEVER feed into the signal engine or the forward test.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, Resources
from app.news.models import NewsFeed

router = APIRouter(prefix="/news", tags=["news"])


@router.get("", response_model=NewsFeed)
async def list_news(_: CurrentUser, resources: Resources) -> NewsFeed:
    if resources.news is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "news_unavailable")
    return resources.news.feed()
