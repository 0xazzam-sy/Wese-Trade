"""Application settings loaded from environment variables / `.env`.

All secrets and environment-specific values come from here. Nothing secret is hardcoded.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]
SECRET_PLACEHOLDER_PREFIX = "CHANGE_ME"  # noqa: S105  (marker used to detect unset secrets)
API_V1_PREFIX = "/api/v1"
API_VERSION = "v1"


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = "NeuralShot"
    app_env: Environment = Environment.DEVELOPMENT
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)

    database_url: str = "sqlite+aiosqlite:///./data/neuralshot.db"

    # Required: no default, so a missing secret fails fast at startup.
    secret_key: str = Field(min_length=32)
    access_token_expire_minutes: int = Field(default=720, ge=5, le=60 * 24 * 30)

    frontend_origin: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Prepared for future phases; unused in phase 1.
    bingx_base_url: str = "https://open-api.bingx.com"
    bingx_ws_url: str = "wss://open-api-swap.bingx.com/swap-market"
    news_provider: str | None = None
    news_api_key: str | None = None

    # WebSocket heartbeat interval (server -> client), seconds.
    ws_heartbeat_seconds: float = Field(default=20.0, gt=0)

    @field_validator("frontend_origin", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip().rstrip("/") for part in value.split(",") if part.strip()]
        return value

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value: object) -> object:
        return value.upper() if isinstance(value, str) else value

    @field_validator("news_provider", "news_api_key", mode="before")
    @classmethod
    def _empty_to_none(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("database_url")
    @classmethod
    def _resolve_sqlite_path(cls, value: str) -> str:
        """Resolve relative SQLite paths against backend/ so the CWD does not matter."""
        prefix, sep, path = value.partition(":///")
        if not sep or not prefix.startswith("sqlite") or path.startswith(":memory:"):
            return value
        db_path = Path(path)
        if not db_path.is_absolute():
            db_path = (BACKEND_DIR / db_path).resolve()
        return f"{prefix}:///{db_path.as_posix()}"

    @model_validator(mode="after")
    def _reject_placeholder_secret_in_production(self) -> Settings:
        if self.is_production and self.secret_key.startswith(SECRET_PLACEHOLDER_PREFIX):
            raise ValueError("SECRET_KEY must be set to a unique random value in production.")
        return self

    @property
    def is_production(self) -> bool:
        return self.app_env is Environment.PRODUCTION

    @property
    def uses_placeholder_secret(self) -> bool:
        return self.secret_key.startswith(SECRET_PLACEHOLDER_PREFIX)

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def sqlite_path(self) -> Path | None:
        if not self.is_sqlite:
            return None
        _, _, path = self.database_url.partition(":///")
        if not path or path.startswith(":memory:"):
            return None
        return Path(path)

    @property
    def cookie_secure(self) -> bool:
        return self.is_production


@lru_cache
def get_settings() -> Settings:
    return Settings()  # values (including the required SECRET_KEY) come from the environment
