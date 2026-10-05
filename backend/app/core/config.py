"""Application settings loaded from environment variables / `.env`.

All secrets and environment-specific values come from here. Nothing secret is hardcoded.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from ipaddress import ip_address
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.runtime import (
    BACKEND_DIR,
    RUNTIME_MODE_ENV,
    RUNTIME_ROOT_ENV,
    RuntimeMode,
    RuntimePaths,
    load_or_create_secret,
    resolve_runtime_paths,
    runtime_mode,
)

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
        populate_by_name=True,
    )

    app_name: str = "Wese Trade"
    app_env: Environment = Environment.DEVELOPMENT
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)

    database_url: str = "sqlite+aiosqlite:///./data/wese_trade.db"

    # Optional: when unset, a per-installation secret file is created under the runtime
    # data directory (owner-only permissions) and reused. It is never logged.
    secret_key: str | None = Field(default=None, min_length=32)

    # Runtime mode / paths (see app/core/runtime.py). The desktop shell sets both.
    runtime_mode: RuntimeMode = Field(
        default=RuntimeMode.DEVELOPMENT, validation_alias=AliasChoices(RUNTIME_MODE_ENV)
    )
    runtime_root: Path | None = Field(default=None, validation_alias=AliasChoices(RUNTIME_ROOT_ENV))
    # Compiled React app served same-origin by the backend (desktop mode).
    web_dir: Path | None = Field(default=None, validation_alias=AliasChoices("WESE_WEB_DIR"))
    # One-time token the desktop shell uses for graceful shutdown (never logged).
    desktop_token: str | None = Field(
        default=None, validation_alias=AliasChoices("WESE_DESKTOP_TOKEN")
    )
    access_token_expire_minutes: int = Field(default=720, ge=5, le=60 * 24 * 30)

    frontend_origin: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Market data: OKX PUBLIC endpoints only. No API key, secret, passphrase or login.
    market_data_enabled: bool = True
    okx_rest_url: str = "https://openapi.okx.com"
    okx_public_ws_url: str = "wss://ws.okx.com/ws/v5/public"  # port 443 (not 8443)
    okx_business_ws_url: str = "wss://ws.okx.com/ws/v5/business"  # candle channels
    market_stale_after_seconds: float = Field(default=60.0, ge=5)

    # News (display only, never consumed by signals). Arabic RSS feeds, comma separated.
    news_enabled: bool = True
    news_feeds: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: [
            "https://ar.cointelegraph.com/rss",
            "https://ar.beincrypto.com/feed/",
        ]
    )
    news_refresh_seconds: float = Field(default=600.0, ge=60)

    # Weather (secondary dashboard utility, never coupled to signals). Open-Meteo: no key.
    weather_enabled: bool = True
    weather_api_url: str = "https://api.open-meteo.com/v1/forecast"
    weather_geocoding_url: str = "https://geocoding-api.open-meteo.com/v1/search"

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

    @field_validator("news_feeds", mode="before")
    @classmethod
    def _split_feeds(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("secret_key", "runtime_root", "web_dir", "desktop_token", mode="before")
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
    def _apply_runtime(self) -> Settings:
        if self.is_desktop:
            if "database_url" not in self.model_fields_set:
                self.database_url = f"sqlite+aiosqlite:///{self.paths.database.as_posix()}"
            if not _is_loopback(self.app_host):
                raise ValueError("desktop mode binds to the loopback interface only")
        if self.secret_key is None:
            self.secret_key = load_or_create_secret(self.paths.secret_file)
        if self.is_production and self.uses_placeholder_secret:
            raise ValueError("SECRET_KEY must be set to a unique random value in production.")
        return self

    @property
    def is_desktop(self) -> bool:
        return self.runtime_mode is RuntimeMode.DESKTOP

    @property
    def paths(self) -> RuntimePaths:
        if self.runtime_root is not None:
            return RuntimePaths(self.runtime_root.expanduser().resolve())
        if self.is_desktop:
            raise ValueError(f"desktop mode requires {RUNTIME_ROOT_ENV}")
        return resolve_runtime_paths({})

    @property
    def signing_key(self) -> str:
        if self.secret_key is None:  # pragma: no cover - the validator always fills it
            raise RuntimeError("secret key not resolved")
        return self.secret_key

    @property
    def is_production(self) -> bool:
        return self.app_env is Environment.PRODUCTION

    @property
    def uses_placeholder_secret(self) -> bool:
        return self.signing_key.startswith(SECRET_PLACEHOLDER_PREFIX)

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
        # Desktop serves the UI same-origin over http://127.0.0.1 (no TLS on loopback).
        return self.is_production and not self.is_desktop


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


@lru_cache
def get_settings() -> Settings:
    if runtime_mode() is RuntimeMode.DESKTOP:
        # Packaged app: configuration comes only from the shell's environment, never from a
        # developer .env file (which could point at a development database).
        return Settings(_env_file=None)
    return Settings()  # values come from the environment / .env
