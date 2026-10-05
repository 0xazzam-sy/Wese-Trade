"""Minimal, safe RSS 2.0 / Atom parsing for Arabic news headlines.

* XML is parsed with ``defusedxml`` (no entity expansion / external entities).
* Only headline, link, publish time and source are kept. HTML is stripped, never rendered.
* Only genuinely Arabic headlines are accepted: Wese Trade never machine-translates or
  generates headlines.
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from xml.etree.ElementTree import Element

from defusedxml import ElementTree

from app.news.models import NewsItem

_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_ARABIC = re.compile(r"[؀-ۿ]")
ATOM = "{http://www.w3.org/2005/Atom}"


def clean_text(value: str | None) -> str:
    text = html.unescape(_TAG.sub(" ", value or ""))
    return _SPACE.sub(" ", text).strip()


def is_arabic(text: str, minimum: float = 0.3) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    return sum(1 for c in letters if _ARABIC.match(c)) / len(letters) >= minimum


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)  # RFC 822 (RSS)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))  # RFC 3339 (Atom)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _text(node: Element | None) -> str | None:
    return node.text if node is not None else None


def _safe_url(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    parsed = urlparse(value)
    return value if parsed.scheme in ("http", "https") and parsed.netloc else None


def parse_feed(payload: bytes, *, feed_url: str) -> list[NewsItem]:
    root = ElementTree.fromstring(payload)
    host = urlparse(feed_url).netloc.removeprefix("www.")
    items: list[NewsItem] = []
    if root.tag == f"{ATOM}feed":
        source = clean_text(_text(root.find(f"{ATOM}title"))) or host
        entries = [
            (
                _text(e.find(f"{ATOM}title")),
                next((link.get("href") for link in e.findall(f"{ATOM}link")), None),
                _text(e.find(f"{ATOM}published")) or _text(e.find(f"{ATOM}updated")),
            )
            for e in root.findall(f"{ATOM}entry")
        ]
    else:
        channel = root.find("channel")
        if channel is None:
            return []
        source = clean_text(_text(channel.find("title"))) or host
        entries = [
            (_text(i.find("title")), _text(i.find("link")), _text(i.find("pubDate")))
            for i in channel.findall("item")
        ]
    for raw_title, raw_link, raw_time in entries:
        title = clean_text(raw_title)
        url = _safe_url(raw_link)
        published = _parse_time(raw_time)
        if not title or url is None or published is None or not is_arabic(title):
            continue
        items.append(
            NewsItem(
                id=hashlib.sha256(url.encode()).hexdigest()[:16],
                title_ar=title[:300],
                source=source[:80],
                published_at=published,
                url=url,
                original_language="ar",
            )
        )
    return items
