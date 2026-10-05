"""Serve the compiled React app same-origin (desktop mode).

Same-origin keeps the httpOnly/SameSite=strict session cookie and the WebSocket origin
check working unchanged, and lets the UI use relative ``/api/v1`` URLs, so the runtime
port is never baked into the build. Security headers (CSP) are added to every response.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import FastAPI, Request, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from app.core.config import API_V1_PREFIX


TAURI_IPC = "ipc: http://ipc.localhost"  # desktop shell IPC (fixed, local-only schemes)


def content_security_policy(host: str, *, desktop: bool = False) -> str:
    ipc = f" {TAURI_IPC}" if desktop else ""
    return "; ".join(
        (
            "default-src 'self'",
            "script-src 'self'",
            # React style attributes; no inline scripts are ever allowed.
            "style-src 'self' 'unsafe-inline'",
            "img-src 'self' data: blob:",
            "font-src 'self' data:",
            # Only the local backend (HTTP + WebSocket). The UI never calls OKX directly.
            f"connect-src 'self' ws://{host} http://{host}{ipc}",
            "object-src 'none'",
            "base-uri 'self'",
            "form-action 'self'",
            "frame-ancestors 'none'",
        )
    )


class SpaStaticFiles(StaticFiles):
    """Static files with an index.html fallback for client-side routes."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or path.startswith("api/") or "." in Path(path).name:
                raise
            return await super().get_response("index.html", scope)


def mount_web(app: FastAPI, web_dir: Path, *, desktop: bool = False) -> None:
    index = web_dir / "index.html"
    if not index.is_file():
        raise RuntimeError(f"compiled web app not found: {index}")

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if not request.url.path.startswith(API_V1_PREFIX):
            response.headers["Content-Security-Policy"] = content_security_policy(
                request.headers.get("host", "127.0.0.1"), desktop=desktop
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
            if request.url.path in ("/", "/index.html") or "." not in request.url.path:
                response.headers["Cache-Control"] = "no-store"
        return response

    app.mount("/", SpaStaticFiles(directory=web_dir, html=True), name="web")
