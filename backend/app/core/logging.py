"""Structured logging.

Development: readable `key=value` lines. Production: one JSON object per line.
Use `logger.info("event.name", extra={"fields": {...}})` to attach structured fields.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "message",
    "fields",
    "color_message",  # uvicorn's ANSI-colored duplicate of the message
}


def _record_fields(record: logging.LogRecord) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    explicit = getattr(record, "fields", None)
    if isinstance(explicit, dict):
        fields.update(explicit)
    for key, value in record.__dict__.items():
        if key not in _RESERVED and not key.startswith("_"):
            fields[key] = value
    return fields


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": _logger_name(record),
            "event": record.getMessage(),
            **_record_fields(record),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def _logger_name(record: logging.LogRecord) -> str:
    # uvicorn logs normal lifecycle INFO lines under "uvicorn.error"; don't make them look alarming.
    return "uvicorn" if record.name == "uvicorn.error" else record.name


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        name = _logger_name(record)
        parts = [f"{ts}Z", f"{record.levelname:<7}", f"{name}:", record.getMessage()]
        parts.extend(f"{k}={v}" for k, v in _record_fields(record).items())
        line = " ".join(parts)
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def configure_logging(level: str, *, json_output: bool) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_output else KeyValueFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Route uvicorn's loggers through the same handler/format.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
    # SQL echo is noisy; enable explicitly when debugging queries.
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    # Per-request exchange logs would flood INFO; our own market.* events cover transitions.
    for noisy in ("httpx", "httpcore", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
