"""Analysis models -> JSON-safe payloads (REST + `analysis.update`).

Floats are rounded to 10 significant digits; enums become their values; times are epoch
seconds already. Computed properties that clients need (zone midpoints) are added here.
"""

from __future__ import annotations

import math
from dataclasses import fields, is_dataclass
from enum import Enum
from typing import Any

from app.analysis.models import AnalysisSnapshot, FairValueGap, OrderBlock, ProtectedLevel

_EXTRA: dict[type, tuple[str, ...]] = {
    FairValueGap: ("mid", "size"),
    OrderBlock: ("mid",),
    ProtectedLevel: ("active",),
}
_SKIP: dict[type, tuple[str, ...]] = {OrderBlock: ("inside",)}


def to_payload(value: Any) -> Any:
    if value is None or isinstance(value, bool | int | str):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return float(f"{value:.10g}")
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value) and not isinstance(value, type):
        skip = _SKIP.get(type(value), ())
        out = {
            f.name: to_payload(getattr(value, f.name)) for f in fields(value) if f.name not in skip
        }
        for name in _EXTRA.get(type(value), ()):
            out[name] = to_payload(getattr(value, name))
        return out
    if isinstance(value, dict):
        return {str(k): to_payload(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [to_payload(v) for v in value]
    raise TypeError(f"cannot serialize {type(value).__name__}")


def snapshot_payload(snapshot: AnalysisSnapshot) -> dict[str, Any]:
    payload = to_payload(snapshot)
    if not isinstance(payload, dict):  # pragma: no cover - a snapshot is a dataclass
        raise TypeError("snapshot did not serialize to an object")
    return payload
