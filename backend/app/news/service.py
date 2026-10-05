"""News feed service (display only).

HARD RULE: news is informational UI only and is NEVER consumed by the signal engine,
forward test, scanner or backtesting (a test enforces the import boundary).

Headlines come from configured Arabic RSS/Atom feeds. They are refreshed in the background,
cached on disk (so the last headlines remain viewable offline, with their real timestamps),
and fail gracefully: an unreachable source is reported, never replaced by invented items.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.core.logging import get_logger
from app.news.models import NewsFeed, NewsItem
from app.news.rss import parse_feed

__all__ = ["NewsFeed", "NewsService"]

logger = get_logger(__name__)
MAX_ITEMS = 40
USER_AGENT = "WeseTrade/1 (+news display)"


class NewsService:
    def __init__(self, settings: Settings, *, cache_file: Path | None = None) -> None:
        self.settings = settings
        self.cache_file = cache_file
        self.items: list[NewsItem] = []
        self.updated_at: datetime | None = None
        self.errors: dict[str, str] = {}
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._last_attempt = 0.0
        self._load_cache()

    # --- lifecycle --------------------------------------------------------------------------
    async def start(self) -> None:
        if self.settings.news_enabled and self.settings.news_feeds and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="news-refresh")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            await self.refresh()
            await asyncio.sleep(self.settings.news_refresh_seconds)

    # --- fetching ---------------------------------------------------------------------------
    async def refresh(self, client: httpx.AsyncClient | None = None) -> None:
        async with self._lock:
            self._last_attempt = time.monotonic()
            own = client is None
            client = client or httpx.AsyncClient(
                timeout=httpx.Timeout(10.0),
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )
            try:
                results = await asyncio.gather(
                    *(self._fetch(client, url) for url in self.settings.news_feeds)
                )
            finally:
                if own:
                    await client.aclose()
            fetched = [item for batch in results if batch for item in batch]
            if any(batch is not None for batch in results):
                merged = {i.id: i for i in [*fetched, *self.items]}  # fresh wins, keep older
                self.items = sorted(merged.values(), key=lambda i: i.published_at, reverse=True)[
                    :MAX_ITEMS
                ]
                self.updated_at = datetime.now(UTC)
                self._save_cache()

    async def _fetch(self, client: httpx.AsyncClient, url: str) -> list[NewsItem] | None:
        try:
            response = await client.get(url)
            response.raise_for_status()
            items = parse_feed(response.content, feed_url=url)
        except Exception as exc:  # network, HTTP, XML: one feed failing never breaks the rest
            self.errors[url] = type(exc).__name__
            logger.warning("news.feed_failed", extra={"fields": {"feed": url, "error": str(exc)}})
            return None
        self.errors.pop(url, None)
        return items

    # --- cache --------------------------------------------------------------------------------
    def _load_cache(self) -> None:
        if self.cache_file is None or not self.cache_file.exists():
            return
        try:
            raw: dict[str, Any] = json.loads(self.cache_file.read_text(encoding="utf-8"))
            self.items = [NewsItem.model_validate(i) for i in raw.get("items", [])]
            stamp = raw.get("updated_at")
            self.updated_at = datetime.fromisoformat(stamp) if stamp else None
        except (OSError, ValueError):
            logger.warning("news.cache_unreadable")

    def _save_cache(self) -> None:
        if self.cache_file is None:
            return
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "updated_at": self.updated_at.isoformat() if self.updated_at else None,
                "items": [i.model_dump(mode="json") for i in self.items],
            }
            tmp = self.cache_file.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.cache_file)
        except OSError:
            logger.warning("news.cache_write_failed")

    # --- API view ----------------------------------------------------------------------------
    def feed(self) -> NewsFeed:
        if not self.settings.news_enabled or not self.settings.news_feeds:
            return NewsFeed(items=[], available=False, message="news_disabled")
        all_failed = bool(self.errors) and len(self.errors) == len(self.settings.news_feeds)
        message = None
        if all_failed:
            message = "news_sources_unreachable"
        elif self.updated_at is None:
            message = "news_loading"
        return NewsFeed(
            items=self.items,
            available=not all_failed or bool(self.items),
            message=message,
            updated_at=self.updated_at,
            stale=all_failed and bool(self.items),
        )
