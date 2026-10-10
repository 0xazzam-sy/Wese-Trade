"""Telegram notification service: settings, recipients, dedupe, delivery with retry.

Isolation: the trading engine calls `notify()`, which only enqueues and never raises or
awaits the network. A background worker matches recipients, inserts one delivery row per
(signal id, recipient, event) — the unique constraint is the dedupe, so restarts and
replays never resend — and sends with bounded retry and exponential backoff. Failures are
recorded in the delivery log and the health state; they never reach the signal engine.

Secrets: the bot token is sealed in the database with a key derived from the
installation signing key, kept decrypted only in memory, and never logged or returned
by the API (only a masked hint).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.secretbox import SecretBoxError, mask, open_, seal
from app.db.session import Database
from app.models.telegram import (
    TelegramDeliveryRecord,
    TelegramRecipientRecord,
    TelegramSettingsRecord,
)
from app.telegram.client import TelegramClient, TelegramError, redact, valid_token_format
from app.telegram.models import (
    DEFAULT_EVENTS,
    EVENTS,
    LIFECYCLE_EVENTS,
    SignalAlert,
    format_alert,
)
from app.utils.time import utc_now

logger = logging.getLogger(__name__)

PURPOSE = "telegram-bot-token"
MAX_ATTEMPTS = 5
BACKOFF = (2.0, 4.0, 8.0, 16.0, 32.0)
RESUME_WINDOW = timedelta(hours=2)  # pending alerts older than this are not sent after restart
MAX_PARALLEL_SENDS = 3

ClientFactory = Callable[[str], TelegramClient]
Sleep = Callable[[float], Awaitable[None]]


@dataclass(slots=True)
class Recipient:
    id: int
    name: str
    chat_id: str
    enabled: bool = True
    buy: bool = True
    sell: bool = True
    timeframes: list[str] = field(default_factory=list)
    symbols: list[str] = field(default_factory=list)
    lifecycle: bool = True

    def wants(self, alert: SignalAlert) -> bool:
        if not self.enabled:
            return False
        if (alert.side == 1 and not self.buy) or (alert.side == -1 and not self.sell):
            return False
        if self.timeframes and alert.timeframe not in self.timeframes:
            return False
        if self.symbols and alert.symbol.upper() not in {s.upper() for s in self.symbols}:
            return False
        return not (alert.event in LIFECYCLE_EVENTS and not self.lifecycle)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "chat_id": self.chat_id,
            "enabled": self.enabled,
            "buy": self.buy,
            "sell": self.sell,
            "timeframes": list(self.timeframes),
            "symbols": list(self.symbols),
            "lifecycle": self.lifecycle,
        }


def _recipient(row: TelegramRecipientRecord) -> Recipient:
    return Recipient(
        row.id, row.name, row.chat_id, row.enabled, row.buy, row.sell,
        list(row.timeframes or []), list(row.symbols or []), row.lifecycle,
    )  # fmt: skip


class TelegramConfigError(ValueError):
    """Invalid admin input (bad token format, unknown recipient...)."""


class TelegramService:
    def __init__(
        self,
        database: Database,
        signing_key: str,
        *,
        client_factory: ClientFactory | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self.database = database
        self._key = signing_key
        self._factory: ClientFactory = client_factory or TelegramClient
        self._sleep = sleep
        self._token: str | None = None
        self.token_hint = ""
        self.bot_username: str | None = None
        self.enabled = True
        self.events: dict[str, bool] = dict(DEFAULT_EVENTS)
        self.status = "not_configured"
        self.status_detail = ""
        self.checked_at: datetime | None = None
        self.recipients: dict[int, Recipient] = {}
        self._queue: asyncio.Queue[SignalAlert] = asyncio.Queue(maxsize=2000)
        self._worker: asyncio.Task[None] | None = None
        self._sends: set[asyncio.Task[None]] = set()
        self._gate = asyncio.Semaphore(MAX_PARALLEL_SENDS)
        self.last_sent_at: datetime | None = None
        self.last_error: str = ""
        self.last_error_at: datetime | None = None
        self.dropped = 0
        self.started = False

    # --- lifecycle ---
    async def start(self) -> None:
        await self._load()
        self._worker = asyncio.create_task(self._run(), name="telegram-dispatcher")
        await self._resume_pending()
        self.started = True

    async def stop(self) -> None:
        self.started = False
        tasks = [t for t in (self._worker, *self._sends) if t is not None]
        for t in tasks:
            t.cancel()
        for t in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self._worker = None
        self._sends.clear()

    async def _load(self) -> None:
        async with self.database.session_factory() as session:
            row = await session.get(TelegramSettingsRecord, 1)
            recips = (await session.execute(select(TelegramRecipientRecord))).scalars().all()
        self.recipients = {r.id: _recipient(r) for r in recips}
        if row is None:
            return
        self.enabled = row.enabled
        self.events = {**DEFAULT_EVENTS, **(row.events or {})}
        self.bot_username = row.bot_username
        self.token_hint = row.token_hint
        self.status, self.status_detail, self.checked_at = (
            row.status,
            row.status_detail,
            row.checked_at,
        )
        if row.token_sealed:
            try:
                self._token = open_(row.token_sealed, self._key, PURPOSE)
            except SecretBoxError as exc:
                self._token = None
                self.status, self.status_detail = "error", f"تعذر فك تخزين الرمز: {exc}"

    async def _save_settings(self, *, token_sealed: str | bool | None = False) -> None:
        async with self.database.session_factory() as session:
            row = await session.get(TelegramSettingsRecord, 1)
            if row is None:
                row = TelegramSettingsRecord(id=1)
                session.add(row)
            if token_sealed is not False:
                row.token_sealed = token_sealed if isinstance(token_sealed, str) else None
            row.token_hint = self.token_hint
            row.bot_username = self.bot_username
            row.enabled = self.enabled
            row.events = dict(self.events)
            row.status = self.status
            row.status_detail = self.status_detail[:255]
            row.checked_at = self.checked_at
            await session.commit()

    # --- engine entry point ---
    def notify(self, alert: SignalAlert) -> None:
        """Non-blocking; safe to call from the signal engine. Never raises."""
        try:
            if not self.started or not self.enabled or not self._token:
                return
            if not self.events.get(alert.event, False) and not alert.test:
                return
            self._queue.put_nowait(alert)
        except asyncio.QueueFull:
            self.dropped += 1
        except Exception:  # pragma: no cover - isolation guarantee
            logger.exception("telegram.notify_failed")

    async def _run(self) -> None:
        while True:
            alert = await self._queue.get()
            try:
                await self._dispatch(alert)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("telegram.dispatch_failed")

    async def _dispatch(self, alert: SignalAlert, only: int | None = None) -> list[int]:
        """Create delivery rows (dedupe) and start sending. Returns the new delivery ids."""
        text = format_alert(alert)
        created: list[int] = []
        for r in list(self.recipients.values()):
            if only is not None and r.id != only:
                continue
            if only is None and not r.wants(alert):
                continue
            async with self.database.session_factory() as session:
                row = TelegramDeliveryRecord(
                    signal_id=alert.signal_id,
                    recipient_id=r.id,
                    event=alert.event,
                    symbol=alert.symbol,
                    timeframe=alert.timeframe,
                    status="pending",
                    attempts=0,
                    last_error="",
                    text=text,
                    test=alert.test,
                )
                session.add(row)
                try:
                    await session.commit()
                except IntegrityError:
                    continue  # already queued/sent for this recipient + event: dedupe
                created.append(row.id)
            self._spawn(row.id, r.chat_id, text)
        return created

    def _spawn(self, delivery_id: int, chat_id: str, text: str) -> None:
        task = asyncio.create_task(self._deliver(delivery_id, chat_id, text))
        self._sends.add(task)
        task.add_done_callback(self._sends.discard)

    async def _deliver(self, delivery_id: int, chat_id: str, text: str) -> None:
        token = self._token
        attempts = 0
        error = ""
        message_id: int | None = None
        status = "failed"
        async with self._gate:
            while token and attempts < MAX_ATTEMPTS:
                attempts += 1
                try:
                    async with self._factory(token) as client:
                        message_id = await client.send_message(chat_id, text)
                    status = "sent"
                    break
                except TelegramError as exc:
                    error = redact(str(exc), token)
                    if not exc.retryable:
                        break
                    await self._sleep(exc.retry_after or BACKOFF[attempts - 1])
                except Exception as exc:  # network stack surprises: retry, never propagate
                    error = redact(f"{type(exc).__name__}: {exc}", token)
                    await self._sleep(BACKOFF[attempts - 1])
            if not token:
                error = "البوت غير مُعدّ"
        now = utc_now()
        async with self.database.session_factory() as session:
            row = await session.get(TelegramDeliveryRecord, delivery_id)
            if row is not None:
                row.status = status
                row.attempts = (row.attempts or 0) + attempts
                row.last_error = error[:255]
                row.message_id = message_id
                row.sent_at = now if status == "sent" else None
                await session.commit()
        if status == "sent":
            self.last_sent_at = now
        else:
            self.last_error, self.last_error_at = error, now
            logger.warning("telegram.delivery_failed id=%s error=%s", delivery_id, error)

    async def _resume_pending(self) -> None:
        """After a restart: finish recent pending deliveries; skip stale ones (no old spam)."""
        cutoff = utc_now() - RESUME_WINDOW
        async with self.database.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(TelegramDeliveryRecord).where(
                            TelegramDeliveryRecord.status == "pending"
                        )
                    )
                )
                .scalars()
                .all()
            )
            resume: list[tuple[int, str, str]] = []
            for row in rows:
                recipient = self.recipients.get(row.recipient_id)
                if row.created_at < cutoff or recipient is None or not self._token:
                    row.status = "skipped"
                    row.last_error = "لم تُرسل: انتهت مهلتها قبل إعادة التشغيل"
                else:
                    resume.append((row.id, recipient.chat_id, row.text))
            await session.commit()
        for delivery_id, chat_id, text in resume:
            self._spawn(delivery_id, chat_id, text)

    async def drain(self) -> None:
        """Wait until queued alerts are dispatched and sends finish (tests / admin)."""
        while not self._queue.empty() or self._sends:
            await asyncio.sleep(0.01)
            if self._sends:
                await asyncio.gather(*list(self._sends), return_exceptions=True)

    # --- admin: bot ------------------------------------------------------------------------
    async def set_token(self, token: str) -> dict[str, Any]:
        token = token.strip()
        if not valid_token_format(token):
            raise TelegramConfigError("صيغة رمز البوت غير صحيحة (مثال: 123456789:ABC...)")
        info = await self._check(token)
        if info is None:
            raise TelegramConfigError(self.status_detail or "تعذر التحقق من رمز البوت")
        self._token = token
        self.token_hint = mask(token)
        await self._save_settings(token_sealed=seal(token, self._key, PURPOSE))
        return self.public()

    async def clear_token(self) -> dict[str, Any]:
        self._token = None
        self.token_hint = ""
        self.bot_username = None
        self.status, self.status_detail = "not_configured", ""
        await self._save_settings(token_sealed=None)
        return self.public()

    async def _check(self, token: str) -> Any:
        self.checked_at = utc_now()
        try:
            async with self._factory(token) as client:
                info = await client.get_me()
        except TelegramError as exc:
            msg = redact(str(exc), token)
            self.status = "error"
            self.status_detail = (
                "رمز البوت مرفوض من Telegram" if "401" in msg or "404" in msg else msg
            )
            return None
        except httpx.HTTPError as exc:  # pragma: no cover - client wraps these
            self.status, self.status_detail = "error", redact(str(exc), token)
            return None
        self.bot_username = info.username
        self.status, self.status_detail = "connected", ""
        return info

    async def test_connection(self) -> dict[str, Any]:
        if not self._token:
            self.status, self.status_detail = "not_configured", ""
        else:
            await self._check(self._token)
            await self._save_settings()
        return self.public()

    async def set_options(
        self, *, enabled: bool | None = None, events: dict[str, bool] | None = None
    ) -> dict[str, Any]:
        if enabled is not None:
            self.enabled = enabled
        if events:
            self.events.update({k: bool(v) for k, v in events.items() if k in EVENTS})
        await self._save_settings()
        return self.public()

    async def send_test_message(self, recipient_id: int | None = None) -> list[dict[str, Any]]:
        """A plain connection test message (status returned per recipient)."""
        if not self._token:
            raise TelegramConfigError("أضف رمز البوت أولاً")
        targets = [
            r for r in self.recipients.values() if recipient_id in (None, r.id) and r.enabled
        ]
        if recipient_id is not None and not targets:
            raise TelegramConfigError("المستلم غير موجود أو غير مفعّل")
        text = (
            "🧪 TEST — Wese Trade\n\nتم ربط البوت بنجاح ✅\n"
            "ستصلك هنا إشارات BUY / SELL المؤكدة وتحديثات الأهداف ووقف الخسارة."
        )
        out: list[dict[str, Any]] = []
        for r in targets:
            try:
                async with self._factory(self._token) as client:
                    mid = await client.send_message(r.chat_id, text)
                out.append({"recipient_id": r.id, "name": r.name, "ok": True, "message_id": mid})
                self.last_sent_at = utc_now()
            except TelegramError as exc:
                err = redact(str(exc), self._token)
                out.append({"recipient_id": r.id, "name": r.name, "ok": False, "error": err})
                self.last_error, self.last_error_at = err, utc_now()
        return out

    async def send_fixture(self, side: int, recipient_id: int | None = None) -> list[int]:
        """A TEST-marked BUY / SELL alert through the real pipeline (dedupe included)."""
        if not self._token:
            raise TelegramConfigError("أضف رمز البوت أولاً")
        stamp = int(utc_now().timestamp())
        alert = fixture_alert(side, stamp)
        ids = await self._dispatch(alert, only=recipient_id) if recipient_id else []
        if recipient_id is None:
            for r in self.recipients.values():
                if r.enabled:
                    ids += await self._dispatch(alert, only=r.id)
        return ids

    async def chat_candidates(self) -> list[dict[str, Any]]:
        """Chats that recently messaged the bot (helps the admin find a chat id)."""
        if not self._token:
            raise TelegramConfigError("أضف رمز البوت أولاً")
        async with self._factory(self._token) as client:
            updates = await client.get_updates()
        seen: dict[str, dict[str, Any]] = {}
        for u in updates:
            msg = u.get("message") or u.get("channel_post") or u.get("my_chat_member") or {}
            chat = msg.get("chat") or {}
            if "id" not in chat:
                continue
            title = chat.get("title") or " ".join(
                x for x in (chat.get("first_name"), chat.get("last_name")) if x
            )
            seen[str(chat["id"])] = {
                "chat_id": str(chat["id"]),
                "type": chat.get("type", ""),
                "title": title or chat.get("username") or "",
            }
        return list(seen.values())

    # --- admin: recipients -------------------------------------------------------------------
    async def add_recipient(self, data: dict[str, Any]) -> dict[str, Any]:
        async with self.database.session_factory() as session:
            row = TelegramRecipientRecord(**_recipient_values(data))
            session.add(row)
            await session.commit()
            rec = _recipient(row)
        self.recipients[rec.id] = rec
        return rec.public()

    async def update_recipient(self, rid: int, data: dict[str, Any]) -> dict[str, Any]:
        async with self.database.session_factory() as session:
            row = await session.get(TelegramRecipientRecord, rid)
            if row is None:
                raise TelegramConfigError("المستلم غير موجود")
            for k, v in _recipient_values(data, partial=True).items():
                setattr(row, k, v)
            await session.commit()
            rec = _recipient(row)
        self.recipients[rid] = rec
        return rec.public()

    async def delete_recipient(self, rid: int) -> None:
        async with self.database.session_factory() as session:
            row = await session.get(TelegramRecipientRecord, rid)
            if row is None:
                raise TelegramConfigError("المستلم غير موجود")
            await session.delete(row)
            await session.commit()
        self.recipients.pop(rid, None)

    async def deliveries(self, limit: int = 50) -> list[dict[str, Any]]:
        async with self.database.session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(TelegramDeliveryRecord)
                        .order_by(TelegramDeliveryRecord.id.desc())
                        .limit(limit)
                    )
                )
                .scalars()
                .all()
            )
        names = {r.id: r.name for r in self.recipients.values()}
        return [
            {
                "id": r.id,
                "signal_id": r.signal_id,
                "recipient_id": r.recipient_id,
                "recipient": names.get(r.recipient_id, "—"),
                "event": r.event,
                "symbol": r.symbol,
                "timeframe": r.timeframe,
                "status": r.status,
                "attempts": r.attempts,
                "error": r.last_error,
                "test": r.test,
                "created_at": r.created_at.isoformat(),
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
            }
            for r in rows
        ]

    # --- views ---
    def public(self) -> dict[str, Any]:
        return {
            "configured": self._token is not None,
            "token_hint": self.token_hint,
            "bot_username": self.bot_username,
            "enabled": self.enabled,
            "events": dict(self.events),
            "status": self.status if self._token else "not_configured",
            "status_detail": self.status_detail,
            "checked_at": self.checked_at.isoformat() if self.checked_at else None,
            "recipients": [r.public() for r in self.recipients.values()],
        }

    async def health(self) -> dict[str, Any]:
        since = utc_now() - timedelta(days=1)
        async with self.database.session_factory() as session:
            counts = dict(
                (
                    await session.execute(
                        select(TelegramDeliveryRecord.status, func.count())
                        .where(TelegramDeliveryRecord.created_at >= since)
                        .group_by(TelegramDeliveryRecord.status)
                    )
                ).all()
            )
        if not self._token:
            state = "not_configured"
        elif not self.enabled:
            state = "disabled"
        elif not any(r.enabled for r in self.recipients.values()):
            state = "no_recipients"
        else:
            state = self.status
        return {
            "state": state,
            "detail": self.status_detail,
            "bot_username": self.bot_username,
            "running": self._worker is not None and not self._worker.done(),
            "recipients": sum(1 for r in self.recipients.values() if r.enabled),
            "sent_24h": int(counts.get("sent", 0)),
            "failed_24h": int(counts.get("failed", 0)),
            "pending": int(counts.get("pending", 0)) + self._queue.qsize(),
            "last_sent_at": self.last_sent_at.isoformat() if self.last_sent_at else None,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at.isoformat() if self.last_error_at else None,
            "dropped": self.dropped,
        }


def _recipient_values(data: dict[str, Any], partial: bool = False) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if "name" in data or not partial:
        name = str(data.get("name", "")).strip()
        if not name:
            raise TelegramConfigError("اسم المستلم مطلوب")
        out["name"] = name[:64]
    if "chat_id" in data or not partial:
        chat = str(data.get("chat_id", "")).strip()
        if not chat or not (chat.lstrip("-").isdigit() or chat.startswith("@")):
            raise TelegramConfigError("Chat ID غير صالح (رقم مثل 123456789 أو -100... أو @channel)")
        out["chat_id"] = chat[:64]
    for key in ("enabled", "buy", "sell", "lifecycle"):
        if key in data:
            out[key] = bool(data[key])
        elif not partial:
            out[key] = True
    for key in ("timeframes", "symbols"):
        if key in data:
            out[key] = [str(x).strip() for x in (data[key] or []) if str(x).strip()]
        elif not partial:
            out[key] = []
    return out


def fixture_alert(side: int, stamp: int) -> SignalAlert:
    """Clearly marked TEST alert with plausible BTC levels (never a real signal)."""
    entry = 84220.0
    risk = 280.0
    d = 1 if side >= 0 else -1
    targets = (entry + d * 350.0, entry + d * 700.0, entry + d * 1190.0)
    rr = tuple(round(abs(t - entry) / risk, 2) for t in targets)
    return SignalAlert(
        signal_id=f"TEST:{'BUY' if d == 1 else 'SELL'}:{stamp}",
        event="NEW",
        symbol="BTCUSDT",
        side=d,
        timeframe="5m",
        primary_timeframe="30m",
        execution_timeframe="5m",
        entry=entry,
        stop=entry - d * risk,
        targets=targets,
        rr=(rr[0], rr[1], rr[2]),
        tier="A",
        score=84,
        timing_score=79,
        family_ar="اختراق وإعادة اختبار",
        signal_time=stamp,
        price_precision=1,
        test=True,
    )


def with_event(alert: SignalAlert, event: str) -> SignalAlert:
    return replace(alert, event=event)
