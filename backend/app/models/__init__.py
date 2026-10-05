"""ORM models. Import every model here so Alembic autogenerate can discover it."""

from app.models.forward_test import (
    ForwardTestCheckpoint,
    ForwardTestCursor,
    ForwardTestOutcome,
    ForwardTestRun,
    ForwardTestSignal,
)
from app.models.signal import BacktestRunRecord, SignalOutcomeRecord, SignalRecord
from app.models.user import User, UserRole

__all__ = [
    "BacktestRunRecord",
    "ForwardTestCheckpoint",
    "ForwardTestCursor",
    "ForwardTestOutcome",
    "ForwardTestRun",
    "ForwardTestSignal",
    "SignalOutcomeRecord",
    "SignalRecord",
    "User",
    "UserRole",
]
