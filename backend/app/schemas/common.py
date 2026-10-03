from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)


class ModuleStatus(ApiModel):
    """Honest status for route groups whose functionality is not implemented yet."""

    module: str
    available: bool
    phase: str
    message: str
