"""ORM models. Import every model here so Alembic autogenerate can discover it."""

from app.models.execution import ExecutionSignalRecord
from app.models.forward_test import (
    ForwardTestCheckpoint,
    ForwardTestCursor,
    ForwardTestOutcome,
    ForwardTestRun,
    ForwardTestSignal,
)
from app.models.signal import BacktestRunRecord, SignalOutcomeRecord, SignalRecord
from app.models.strategy43 import Strategy43CursorRecord, Strategy43SignalRecord
from app.models.telegram import (
    TelegramDeliveryRecord,
    TelegramRecipientRecord,
    TelegramSettingsRecord,
)
from app.models.user import User, UserRole

__all__ = [
    "BacktestRunRecord",
    "ExecutionSignalRecord",
    "ForwardTestCheckpoint",
    "ForwardTestCursor",
    "ForwardTestOutcome",
    "ForwardTestRun",
    "ForwardTestSignal",
    "SignalOutcomeRecord",
    "SignalRecord",
    "Strategy43CursorRecord",
    "Strategy43SignalRecord",
    "TelegramDeliveryRecord",
    "TelegramRecipientRecord",
    "TelegramSettingsRecord",
    "User",
    "UserRole",
]
