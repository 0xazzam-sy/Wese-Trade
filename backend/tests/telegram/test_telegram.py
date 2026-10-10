"""Telegram notifications: secret storage, redaction, filters, dedupe, retry, restart."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any, ClassVar

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.core.secretbox import SecretBoxError, mask, open_, seal
from app.db.base import Base
from app.db.session import Database
from app.models.telegram import TelegramDeliveryRecord, TelegramSettingsRecord
from app.telegram.client import BotInfo, TelegramError, redact, valid_token_format
from app.telegram.models import SignalAlert, format_alert
from app.telegram.service import TelegramConfigError, TelegramService, fixture_alert

TOKEN = "123456789:AAEexampleexampleexampleexampleXYZ"  # fake, valid format
KEY = "k" * 48


class FakeBot:
    """Stands in for TelegramClient; records messages, fails on demand."""

    sent: ClassVar[list[tuple[str, str]]] = []
    fail: ClassVar[list[TelegramError]] = []
    me_error: ClassVar[TelegramError | None] = None

    def __init__(self, token: str) -> None:
        self.token = token

    async def __aenter__(self) -> FakeBot:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def get_me(self) -> BotInfo:
        if FakeBot.me_error is not None:
            raise FakeBot.me_error
        return BotInfo(1, "wese_test_bot", "Wese")

    async def send_message(self, chat_id: str, text: str) -> int:
        if FakeBot.fail:
            raise FakeBot.fail.pop(0)
        FakeBot.sent.append((chat_id, text))
        return len(FakeBot.sent)

    async def get_updates(self) -> list[dict[str, Any]]:
        return [{"message": {"chat": {"id": 42, "type": "private", "first_name": "Ali"}}}]


@pytest.fixture(autouse=True)
def _reset_bot() -> None:
    FakeBot.sent = []
    FakeBot.fail = []
    FakeBot.me_error = None


@pytest.fixture
async def database(settings: Settings) -> AsyncIterator[Database]:
    db = Database(settings)
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield db
    await db.dispose()


async def _no_sleep(_: float) -> None:
    return None


async def service(database: Database) -> TelegramService:
    svc = TelegramService(database, KEY, client_factory=FakeBot, sleep=_no_sleep)  # type: ignore[arg-type]
    await svc.start()
    return svc


def alert(event: str = "NEW", side: int = 1, **changes: Any) -> SignalAlert:
    base = SignalAlert(
        signal_id="BTCUSDT:30m:1", event=event, symbol="BTCUSDT", side=side, timeframe="30m",
        primary_timeframe="30m", execution_timeframe=None, entry=84220.0, stop=83940.0,
        targets=(84570.0, 84920.0, 85410.0), rr=(1.25, 2.5, 4.25), tier="A", score=84.0,
        timing_score=None, family_ar="استمرار الاتجاه", signal_time=1_790_000_000,
        price_precision=1,
    )  # fmt: skip
    return replace(base, **changes)


def test_secretbox_roundtrip_and_tamper() -> None:
    sealed = seal(TOKEN, KEY, "telegram-bot-token")
    assert TOKEN not in sealed
    assert open_(sealed, KEY, "telegram-bot-token") == TOKEN
    with pytest.raises(SecretBoxError):
        open_(sealed, "other" * 10, "telegram-bot-token")
    with pytest.raises(SecretBoxError):
        open_(sealed[:-4] + "AAAA", KEY, "telegram-bot-token")
    assert mask(TOKEN) == "••••XYZ"[:0] + "••••" + TOKEN[-4:]
    assert TOKEN not in mask(TOKEN)


def test_token_format_and_redaction() -> None:
    assert valid_token_format(TOKEN)
    assert not valid_token_format("not-a-token")
    text = f"POST https://api.telegram.org/bot{TOKEN}/sendMessage failed"
    assert TOKEN not in redact(text)
    assert TOKEN not in redact(text, TOKEN)


def test_message_format_has_every_required_field() -> None:
    text = format_alert(alert())
    labels = (
        "العملة:", "BTCUSDT", "BUY — شراء", "الفريم الأساسي:", "30m", "جودة الفرصة:",
        "A — قوية", "قوة الإشارة:", "84 / 100", "سعر الدخول:", "84,220.0", "وقف الخسارة:",
        "TP1:", "TP2:", "TP3:", "R:R:", "نوع الفرصة:", "وقت الإشارة:",
    )  # fmt: skip
    for label in labels:
        assert label in text
    exec_text = format_alert(alert(execution_timeframe="5m", timing_score=79.0, side=-1))
    assert "توقيت الدخول:" in exec_text and "قوة توقيت الدخول:" in exec_text
    assert "SELL — بيع" in exec_text
    assert "TEST" in format_alert(fixture_alert(1, 1))
    assert "TEST" not in text


async def test_token_is_sealed_never_returned_and_status_connected(
    database: Database, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    svc = await service(database)
    with pytest.raises(TelegramConfigError):
        await svc.set_token("bad")
    out = await svc.set_token(TOKEN)
    assert out["status"] == "connected" and out["bot_username"] == "wese_test_bot"
    assert TOKEN not in str(out)
    async with database.session_factory() as s:
        row = await s.get(TelegramSettingsRecord, 1)
        assert row is not None and row.token_sealed and TOKEN not in row.token_sealed
    assert TOKEN not in caplog.text
    await svc.stop()
    again = await service(database)  # restart restores the token from the sealed copy
    assert again.public()["configured"] is True
    await again.stop()


async def test_rejected_token_reports_error(database: Database) -> None:
    FakeBot.me_error = TelegramError("401: Unauthorized", retryable=False)
    svc = await service(database)
    with pytest.raises(TelegramConfigError):
        await svc.set_token(TOKEN)
    assert svc.public()["configured"] is False
    await svc.stop()


async def test_filters_dedupe_and_restart_never_resends(database: Database) -> None:
    svc = await service(database)
    await svc.set_token(TOKEN)
    a = await svc.add_recipient({"name": "Ali", "chat_id": "42"})
    b = await svc.add_recipient({"name": "Sells 1h", "chat_id": "-100777", "buy": False,
                                 "timeframes": ["1h"]})  # fmt: skip
    c = await svc.add_recipient({"name": "No lifecycle", "chat_id": "43", "lifecycle": False})
    svc.notify(alert())
    svc.notify(alert())  # duplicate: same signal + event
    svc.notify(alert(event="TP1"))
    await svc.drain()
    chats = [chat for chat, _ in FakeBot.sent]
    assert chats.count("42") == 2  # NEW + TP1
    assert "-100777" not in chats  # BUY filtered out, and 30m not in its timeframes
    assert chats.count("43") == 1  # NEW only: lifecycle alerts disabled
    await svc.stop()
    restarted = await service(database)
    restarted.notify(alert())
    restarted.notify(alert(event="TP1"))
    await restarted.drain()
    assert len(FakeBot.sent) == 3  # nothing resent after restart
    async with database.session_factory() as s:
        rows = (await s.execute(select(TelegramDeliveryRecord))).scalars().all()
    assert {(r.recipient_id, r.event) for r in rows} == {
        (a["id"], "NEW"), (a["id"], "TP1"), (c["id"], "NEW")
    }  # fmt: skip
    assert all(r.status == "sent" for r in rows)
    assert b["buy"] is False
    await restarted.stop()


async def test_expired_alerts_off_by_default(database: Database) -> None:
    svc = await service(database)
    await svc.set_token(TOKEN)
    await svc.add_recipient({"name": "Ali", "chat_id": "42"})
    svc.notify(alert(event="EXPIRED"))
    svc.notify(alert(event="STOPPED"))
    await svc.drain()
    assert len(FakeBot.sent) == 1 and "ضُرب وقف الخسارة" in FakeBot.sent[0][1]
    await svc.stop()


async def test_retry_backoff_then_failure_state(database: Database) -> None:
    svc = await service(database)
    await svc.set_token(TOKEN)
    await svc.add_recipient({"name": "Ali", "chat_id": "42"})
    FakeBot.fail = [TelegramError("network error", retryable=True)] * 2
    svc.notify(alert())
    await svc.drain()
    assert len(FakeBot.sent) == 1  # delivered on the third attempt
    FakeBot.fail = [TelegramError("400: chat not found", retryable=False)]
    svc.notify(alert(signal_id="ETH:1h:9"))
    await svc.drain()
    log = await svc.deliveries()
    failed = [d for d in log if d["status"] == "failed"]
    assert len(failed) == 1 and failed[0]["attempts"] == 1
    health = await svc.health()
    assert health["failed_24h"] == 1 and health["sent_24h"] == 1
    assert "chat not found" in health["last_error"]
    await svc.stop()


async def test_notify_never_raises_without_configuration(database: Database) -> None:
    svc = await service(database)
    svc.notify(alert())  # not configured: silently ignored
    await svc.drain()
    assert FakeBot.sent == []
    await svc.stop()
    svc.notify(alert())  # stopped: still never raises


async def test_fixtures_are_marked_test_and_chat_discovery(database: Database) -> None:
    svc = await service(database)
    await svc.set_token(TOKEN)
    await svc.add_recipient({"name": "Ali", "chat_id": "42"})
    await svc.send_fixture(1)
    await svc.send_fixture(-1)
    await svc.drain()
    assert len(FakeBot.sent) == 2
    assert all(text.startswith("🧪 TEST") for _, text in FakeBot.sent)
    assert "BUY — شراء" in FakeBot.sent[0][1] and "SELL — بيع" in FakeBot.sent[1][1]
    assert (await svc.chat_candidates())[0]["chat_id"] == "42"
    result = await svc.send_test_message()
    assert result[0]["ok"] is True
    await svc.stop()


async def test_recipient_validation(database: Database) -> None:
    svc = await service(database)
    with pytest.raises(TelegramConfigError):
        await svc.add_recipient({"name": "", "chat_id": "42"})
    with pytest.raises(TelegramConfigError):
        await svc.add_recipient({"name": "x", "chat_id": "abc"})
    r = await svc.add_recipient({"name": "x", "chat_id": "@wese_channel"})
    upd = await svc.update_recipient(r["id"], {"enabled": False, "symbols": ["btcusdt"]})
    assert upd["enabled"] is False and upd["symbols"] == ["btcusdt"]
    await svc.delete_recipient(r["id"])
    assert svc.public()["recipients"] == []
    await svc.stop()
