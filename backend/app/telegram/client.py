"""Minimal Telegram Bot API client (getMe, sendMessage). The token never appears in logs
or exception text: every error is rewritten with the token redacted."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import httpx

API = "https://api.telegram.org"
TOKEN_RE = re.compile(r"^\d{5,16}:[A-Za-z0-9_-]{30,64}$")
_ANY_TOKEN = re.compile(r"\d{5,16}:[A-Za-z0-9_-]{30,64}")


def redact(text: str, token: str | None = None) -> str:
    if token:
        text = text.replace(token, "<redacted>")
    return _ANY_TOKEN.sub("<redacted>", text)


def valid_token_format(token: str) -> bool:
    return bool(TOKEN_RE.match(token.strip()))


class TelegramError(Exception):
    def __init__(self, message: str, *, retryable: bool, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


@dataclass(frozen=True, slots=True)
class BotInfo:
    id: int
    username: str
    name: str


class TelegramClient:
    def __init__(self, token: str, client: httpx.AsyncClient | None = None) -> None:
        self._token = token.strip()
        self._client = client
        self._own = client is None

    async def __aenter__(self) -> TelegramClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0))
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._own and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _call(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        assert self._client is not None, "use `async with TelegramClient(...)`"  # noqa: S101
        url = f"{API}/bot{self._token}/{method}"
        try:
            resp = await self._client.post(url, json=payload or {})
        except httpx.HTTPError as exc:
            raise TelegramError(
                redact(f"network error: {type(exc).__name__}: {exc}", self._token), retryable=True
            ) from None
        try:
            body = resp.json()
        except ValueError:
            body = {}
        if resp.status_code == 200 and body.get("ok"):
            return body.get("result")
        desc = redact(str(body.get("description") or resp.reason_phrase), self._token)
        if resp.status_code == 429:
            after = float((body.get("parameters") or {}).get("retry_after", 5))
            raise TelegramError(f"rate limited: {desc}", retryable=True, retry_after=after)
        if resp.status_code >= 500:
            raise TelegramError(f"telegram server error {resp.status_code}: {desc}", retryable=True)
        raise TelegramError(f"{resp.status_code}: {desc}", retryable=False)

    async def get_me(self) -> BotInfo:
        r = await self._call("getMe")
        return BotInfo(int(r["id"]), str(r.get("username", "")), str(r.get("first_name", "")))

    async def send_message(self, chat_id: str, text: str) -> int:
        r = await self._call(
            "sendMessage",
            {"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        )
        return int(r["message_id"])

    async def get_updates(self) -> list[dict[str, Any]]:
        """Recent updates (used by the admin helper to discover chat ids)."""
        r = await self._call("getUpdates", {"limit": 50, "timeout": 0})
        return list(r or [])
