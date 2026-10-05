# PyInstaller spec: Wese Trade backend sidecar (one-folder build).
#
# One-folder (not one-file) on purpose: a single process (no bootloader child that could
# be orphaned), no extraction to a temp dir on every launch, faster startup, and every
# binary can be code-signed for notarization. Built per platform from the same source:
#
#     python ../scripts/build_sidecar.py
#
# Included: the app package (FastAPI, Uvicorn, SQLAlchemy, Alembic + migrations, Argon2,
# OKX provider, analysis, signal engine, forward test, news, weather) and the compiled
# React app (web/). Excluded: tests, research databases, caches, developer .env files.
import os
from PyInstaller.utils.hooks import collect_submodules

BACKEND = os.path.abspath(os.path.join(SPECPATH, ".."))
ROOT = os.path.abspath(os.path.join(BACKEND, ".."))
WEB = os.environ.get("WESE_WEB_BUILD", os.path.join(ROOT, "frontend", "dist"))
if not os.path.isfile(os.path.join(WEB, "index.html")):
    raise SystemExit(f"compiled frontend not found at {WEB}: run `npm run build` in frontend/")

hiddenimports = (
    collect_submodules("app")
    + collect_submodules("uvicorn")
    + collect_submodules("alembic")
    + [
        "aiosqlite",
        "sqlalchemy.dialects.sqlite.aiosqlite",
        "sqlalchemy.dialects.sqlite.pysqlite",
        "argon2",
        "argon2._ffi",
        "_cffi_backend",
        "defusedxml.ElementTree",
        "websockets.legacy",
        "websockets.asyncio.client",
        "websockets.asyncio.server",
        "httptools",
        "email.utils",
    ]
)

a = Analysis(
    [os.path.join(BACKEND, "app", "desktop.py")],
    pathex=[BACKEND],
    binaries=[],
    datas=[
        (os.path.join(BACKEND, "alembic"), "alembic"),
        (WEB, "web"),
    ],
    hiddenimports=hiddenimports,
    excludes=["tests", "pytest", "mypy", "ruff", "tkinter", "matplotlib", "numpy", "IPython"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="wese-trade-backend",
    console=True,  # no window is shown: the shell starts it with CREATE_NO_WINDOW / no tty
    disable_windowed_traceback=False,
    strip=False,
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="backend")
