"""Runtime information and the desktop shell's graceful-shutdown hook."""

from __future__ import annotations

import hmac
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app import __version__
from app.api.deps import CurrentUser, Resources, get_current_user
from app.forward_test.candidate import DISPLAY_NAME
from app.models.user import UserRole

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/runtime", dependencies=[Depends(get_current_user)])
async def runtime(resources: Resources, user: CurrentUser) -> dict[str, Any]:
    settings = resources.settings
    forward = resources.forward_test
    payload: dict[str, Any] = {
        "app_version": __version__,
        "mode": settings.runtime_mode.value,
        "market_provider": "OKX",
        "strategy": {
            "name": DISPLAY_NAME,
            "version": forward.version if forward else None,
            "fingerprint": forward.fingerprint if forward else None,
            "status": forward.run.status if forward and forward.run else None,
        },
        "news_enabled": settings.news_enabled,
        "weather_enabled": settings.weather_enabled,
    }
    if settings.is_desktop and user.role in (UserRole.ADMIN, UserRole.ANALYST):
        paths = settings.paths
        payload["paths"] = {
            "root": str(paths.root),
            "data": str(paths.data),
            "logs": str(paths.logs),
            "exports": str(paths.exports),
            "backups": str(paths.backups),
        }
    return payload


@router.post("/shutdown", status_code=status.HTTP_202_ACCEPTED)
async def shutdown(
    resources: Resources,
    token: Annotated[str | None, Header(alias="X-Wese-Desktop-Token")] = None,
) -> dict[str, str]:
    """Desktop only: the shell asks the sidecar to stop gracefully (flush, cursors, close)."""
    expected = resources.settings.desktop_token
    if (
        not resources.settings.is_desktop
        or expected is None
        or token is None
        or not hmac.compare_digest(token, expected)
        or resources.request_shutdown is None
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "not_found")
    resources.request_shutdown()
    return {"status": "shutting_down"}
