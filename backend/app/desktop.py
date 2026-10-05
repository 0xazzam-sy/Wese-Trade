"""Desktop sidecar entrypoint (packaged with PyInstaller; started by the Tauri shell).

Contract with the shell (see docs/desktop.md):

* env ``WESE_RUNTIME_MODE=desktop``, ``WESE_RUNTIME_ROOT=<native app-data dir>``,
  ``WESE_PORT=<free loopback port>``, ``WESE_DESKTOP_TOKEN=<random per launch>``.
* Binds ONLY to 127.0.0.1. Prepares the database (backup + migrate) BEFORE serving.
* Graceful stop: ``POST /api/v1/system/shutdown`` (token header), SIGINT/SIGTERM, or
  stdin EOF (the shell holds the pipe, so if the shell dies the sidecar exits too:
  no orphan process).
* Exit codes: 0 ok, 2 configuration error, 3 database migration failed, 4 port in use.
"""

from __future__ import annotations

import errno
import os
import socket
import sys
import threading
from pathlib import Path

EXIT_CONFIG = 2
EXIT_MIGRATION = 3
EXIT_PORT = 4
LOOPBACK = "127.0.0.1"


def _bundled_web_dir() -> Path | None:
    base = getattr(sys, "_MEIPASS", None)
    if base is None:
        return None
    web = Path(base) / "web"
    return web if (web / "index.html").is_file() else None


def _bind(port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if sys.platform != "win32":
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((LOOPBACK, port))
    sock.listen(128)
    sock.set_inheritable(True)
    return sock


def main() -> int:
    os.environ.setdefault("WESE_RUNTIME_MODE", "desktop")
    os.environ.setdefault("APP_ENV", "production")
    if (web := _bundled_web_dir()) is not None:
        os.environ.setdefault("WESE_WEB_DIR", str(web))

    from app.core.config import get_settings
    from app.core.logging import configure_logging, get_logger
    from app.db.migrate import MigrationError, prepare_database

    try:
        settings = get_settings()
        paths = settings.paths.ensure()
    except Exception as exc:
        print(f"wese-trade: configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    configure_logging(settings.log_level, json_output=True, log_dir=paths.logs)
    logger = get_logger("app.desktop")

    db_path = settings.sqlite_path
    if db_path is None:
        print("wese-trade: desktop mode requires SQLite", file=sys.stderr)
        return EXIT_CONFIG
    try:
        result = prepare_database(db_path, paths.backups)
    except MigrationError as exc:
        logger.error("desktop.migration_failed", extra={"fields": {"error": str(exc)}})
        print(f"wese-trade: {exc}", file=sys.stderr)
        return EXIT_MIGRATION
    logger.info(
        "desktop.database_ready",
        extra={"fields": {"from": result.from_revision, "to": result.to_revision}},
    )

    port = int(os.environ.get("WESE_PORT", "0"))
    try:
        sock = _bind(port)
    except OSError as exc:
        print(f"wese-trade: cannot bind {LOOPBACK}:{port}: {exc}", file=sys.stderr)
        return EXIT_PORT if exc.errno in (errno.EADDRINUSE, 10048) else EXIT_CONFIG
    port = sock.getsockname()[1]

    import uvicorn

    from app.main import create_app

    app = create_app(settings)
    config = uvicorn.Config(
        app,
        log_config=None,
        lifespan="on",
        timeout_graceful_shutdown=8,
        ws_ping_interval=None,  # the app's own heartbeat is used
    )
    server = uvicorn.Server(config)

    def request_shutdown() -> None:
        server.should_exit = True

    app.state.resources.request_shutdown = request_shutdown

    if os.environ.get("WESE_STDIN_WATCHDOG") == "1":

        def watch_parent() -> None:
            # Raw fd reads (no buffered-stdin lock: safe at interpreter shutdown).
            try:
                while os.read(0, 1024):
                    pass
            except OSError:
                pass
            logger.info("desktop.parent_gone")
            request_shutdown()

        threading.Thread(target=watch_parent, name="parent-watchdog", daemon=True).start()

    logger.info("desktop.serving", extra={"fields": {"host": LOOPBACK, "port": port}})
    server.run(sockets=[sock])
    logger.info("desktop.stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
