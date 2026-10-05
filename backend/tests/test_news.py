"""Real news pipeline (offline fixtures): safe parsing, Arabic only, graceful failure, cache."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from app.core.config import Settings
from app.news.rss import is_arabic, parse_feed
from app.news.service import NewsService

FIXTURES = Path(__file__).parent / "fixtures"
APP = Path(__file__).resolve().parents[1] / "app"


def test_parse_rss_keeps_safe_arabic_items_only() -> None:
    items = parse_feed(
        (FIXTURES / "news_rss.xml").read_bytes(), feed_url="https://ar.example.com/rss"
    )
    assert [i.title_ar for i in items] == [
        "البيتكوين يرتفع فوق مستوى & مقاومة رئيسية",  # HTML stripped, entities decoded
        "الإيثريوم يستقر بعد التحديث",
    ]
    assert items[0].source == "كوينتلغراف بالعربية"
    assert items[0].published_at == datetime(2026, 10, 5, 8, 0, tzinfo=UTC)
    assert items[1].published_at == datetime(2026, 10, 5, 6, 15, tzinfo=UTC)  # tz -> UTC
    assert all(str(i.url).startswith("https://") for i in items)


def test_parse_atom() -> None:
    items = parse_feed(
        (FIXTURES / "news_atom.xml").read_bytes(), feed_url="https://ar.example.org/f"
    )
    assert len(items) == 1 and items[0].source == "بي إن كريبتو"


def test_xml_bombs_are_rejected() -> None:
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;">]><rss>&b;</rss>'
    )
    with pytest.raises(Exception):  # noqa: B017, PT011  (defusedxml refuses entities)
        parse_feed(bomb, feed_url="https://x.example")


def test_is_arabic() -> None:
    assert is_arabic("سعر البيتكوين BTC اليوم")
    assert not is_arabic("Bitcoin price today")


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        secret_key="s" * 40,
        news_feeds=["https://ar.example.com/rss", "https://ar.example.org/atom"],
        runtime_root=tmp_path,
        _env_file=None,
    )


async def test_service_refresh_failure_and_cache(tmp_path: Path) -> None:
    online = {"ok": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if not online["ok"]:
            raise httpx.ConnectError("offline", request=request)
        name = "news_rss.xml" if "rss" in request.url.path else "news_atom.xml"
        return httpx.Response(200, content=(FIXTURES / name).read_bytes())

    cache = tmp_path / "cache" / "news.json"
    service = NewsService(_settings(tmp_path), cache_file=cache)
    assert service.feed().message == "news_loading"
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await service.refresh(client)
        feed = service.feed()
        assert feed.available and feed.message is None and not feed.stale
        assert feed.items[0].title_ar == "البيتكوين يرتفع فوق مستوى & مقاومة رئيسية"
        assert len(feed.items) == 3  # newest first, from both sources
        online["ok"] = False
        await service.refresh(client)
    offline = service.feed()
    assert offline.stale and offline.message == "news_sources_unreachable"
    assert len(offline.items) == 3  # last real headlines kept, never invented ones

    reloaded = NewsService(_settings(tmp_path), cache_file=cache)  # restart while offline
    assert [i.id for i in reloaded.feed().items] == [i.id for i in offline.items]


async def test_unreachable_without_cache_is_honest(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    service = NewsService(_settings(tmp_path))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await service.refresh(client)
    feed = service.feed()
    assert feed.items == [] and feed.available is False
    assert feed.message == "news_sources_unreachable"


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(a.name for a in node.names)
    return names


@pytest.mark.parametrize(
    "package", ["signal_engine", "forward_test", "analysis", "research", "backtesting"]
)
def test_news_and_weather_never_reach_signals(package: str) -> None:
    for file in (APP / package).rglob("*.py"):
        bad = {m for m in _imports(file) if m.startswith(("app.news", "app.weather"))}
        assert not bad, f"{file} imports {bad}"
