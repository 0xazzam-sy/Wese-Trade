# Wese Trade Desktop (Phase 4.3)

Wese Trade ships as one desktop application for **Windows x64** and **macOS Apple
Silicon**, built from a single shared codebase:

- **Tauri 2** desktop shell (Rust, `desktop/src-tauri`);
- the existing **FastAPI** backend, packaged with **PyInstaller** as a standalone sidecar;
- the existing **React/Vite** UI;
- **SQLite**.

End users need no Python, pip, virtualenv, Node, npm or terminal.

> Analysis only. No orders, no exchange accounts, no private exchange APIs.
> The app version (**1.0.0**, SemVer) is separate from the frozen strategy version
> **`wese-trade-forward-4.2-a03e20f1d4`**, which is unchanged.

## 1. Architecture

```
Wese Trade.app / wese-trade.exe  (Tauri shell, Rust)
 ├─ resolves the native app-data dir, creates data/ logs/ cache/ exports/ backups/
 ├─ picks a free port on 127.0.0.1 and starts the sidecar:
 │    backend/wese-trade-backend   (PyInstaller one-folder; embedded Python)
 │      ├─ backs up the DB if a migration is needed, runs Alembic, restores on failure
 │      ├─ binds 127.0.0.1:<port> only; Host allowlist = loopback names
 │      ├─ OKX market data · analysis · signals · forward test · news · weather
 │      └─ serves the compiled React app SAME-ORIGIN (web/) with a strict CSP
 ├─ waits for GET /api/v1/health, then points the window at http://127.0.0.1:<port>/
 ├─ watches the sidecar: crash → Arabic crash page (restart service / logs / restart app)
 └─ on exit: graceful shutdown hook → bounded wait → forced kill fallback
```

**Why the UI is served by the sidecar.** Authentication uses an httpOnly
`SameSite=Strict` cookie. A page served from `tauri://localhost` would be cross-origin with
`http://127.0.0.1:<port>`, and that cookie would not be sent. Serving the compiled assets
same-origin keeps the existing auth security unchanged. It also makes every URL relative
(`/api/v1`, `/api/v1/ws`), so the runtime port never needs a rebuild.

It is still a static production build: no Vite dev server runs in production.

The bundled local page (`desktop/ui/`) is only the splash, startup-error and crash screen.

## 2. Runtime paths

The data root is resolved **once**, natively, by the shell (`dirs::data_local_dir()`, the
same resolver Tauri uses). It is passed to the backend as `WESE_RUNTIME_ROOT`. The backend
has one canonical path module, `backend/app/core/runtime.py`, and no OS checks are
scattered through the Python code.

| OS | Root |
| --- | --- |
| Windows | `%LOCALAPPDATA%\WeseTrade\` |
| macOS | `~/Library/Application Support/WeseTrade/` |

```
data/      wese_trade.db (+ -wal/-shm), secret_key (per-installation, 0600, never logged)
logs/      desktop.log (shell), backend.log, forward-test.log, backend-stderr.log (rotated)
cache/     news.json (last real headlines for offline viewing)
exports/   (CSV/JSON exports)
backups/   wese_trade-<UTC>-before-<revision>.db (last 10 kept)
```

Nothing mutable is ever written into the installation directory. Paths with spaces and
non-ASCII user names (e.g. `C:\Users\مستخدم تجريبي`) are tested.

In development (`WESE_RUNTIME_MODE` unset) the backend keeps the repository layout
(`backend/data/…`) and `backend/.env`. Desktop mode **ignores `.env` files**, so a developer
database can never be picked up by the packaged app.

## 3. Startup lifecycle

1. The shell starts. Single-instance check: a second launch only focuses the existing
   window.
2. The app-data directories are created.
3. A free loopback port is chosen. If the sidecar reports "port in use" (exit 4), the shell
   retries with a new port.
4. The sidecar starts with `WESE_RUNTIME_MODE=desktop`, `WESE_RUNTIME_ROOT`, `WESE_PORT`
   and a per-launch `WESE_DESKTOP_TOKEN`. Its stdin is a pipe held by the shell.
5. **Database preparation** (`app/db/migrate.py`):
   - read the current revision;
   - if a migration is needed and the DB holds data, take a consistent SQLite online
     backup;
   - run `alembic upgrade head`;
   - on failure, restore the backup into the DB, then exit with code 3. The UI shows
     «فشل تحديث قاعدة البيانات…». The DB is never deleted.
6. The services start: OKX, analysis, signals, the forward test (see §6) and news.
7. `/api/v1/health` answers 200 and the shell navigates the window to the app.
8. **First run** with no users shows «الإعداد الأول». The first administrator is created in
   the UI. Further users are managed in Settings → المستخدمون. No terminal is needed.

Startup errors are shown in Arabic with three buttons: «إعادة تشغيل الخدمة», «فتح السجلات»
and «إعادة تشغيل التطبيق».

## 4. Shutdown, crash recovery, orphans

- **Normal exit** (window closed or quit):
  1. `POST /api/v1/system/shutdown` with the per-launch token; this route exists only in
     desktop mode;
  2. uvicorn stops gracefully. The forward test flushes its write queue, which persists
     signals and cursors. OKX sockets close and the DB is disposed;
  3. the shell waits up to 15 s, then force-kills if needed;
  4. the shell exits.
- **The shell dies** (crash, Task Manager, SIGKILL): the stdin pipe closes. The sidecar's
  watchdog notices, logs `desktop.parent_gone` and shuts down gracefully. Tested: the
  sidecar exited about 3 s after a SIGKILL of the shell, with no orphan left.
- **The sidecar crashes**: the monitor detects it within 0.5 s and the window shows
  «تعطلت خدمة Wese Trade المحلية» with restart service, open logs and restart app.
  "Restart service" starts a new sidecar and returns to the app.
- **The sidecar is one process**: one-folder PyInstaller has no bootloader child that could
  be orphaned. On Windows it starts with `CREATE_NO_WINDOW`.

## 5. Security

- **Network exposure**
  - Loopback only: `127.0.0.1`. Desktop settings refuse any other host.
  - Trusted-host middleware rejects non-loopback `Host` headers (DNS-rebinding defence).
  - The WebSocket accepts only the server's own loopback origin.
- **Tauri capabilities** (`desktop/src-tauri/capabilities/`):
  - `local-shell` (bundled splash/crash page): `startup_status`, `restart_backend`,
    `open_logs_dir`, `restart_app`, `quit_app`.
  - `app-ui` (the UI on `http://127.0.0.1:*`): `open_data_dir`, `open_logs_dir`,
    `open_external_url` (http/https only, non-local), `check_for_updates`,
    `install_update`, `smoke_report` (a no-op outside the CI smoke mode).
  - **No** shell, filesystem, process or HTTP plugin permissions are granted. The frontend
    cannot launch programs; only the sidecar lifecycle exists, and it is driven from Rust.
- **Navigation**
  - The window can only show the local UI.
  - Other links (e.g. news sources) open in the system browser.
  - New-window requests are denied.
- **CSP**
  - Shell page: `default-src 'self'`, no inline scripts, IPC only.
  - UI served by the sidecar: `script-src 'self'`; `connect-src` is self, the loopback
    HTTP/WS origin and Tauri IPC. The UI never connects to OKX directly.
- **Secrets**
  - The JWT signing secret is generated per installation (`data/secret_key`, 0600) and never
    logged.
  - No API keys are needed.
  - No private keys are in the repository (a test checks this).

## 6. Forward test on the desktop (permanent local run)

The desktop installation keeps its own forward test in its own database:

- **No local run open:** a **new** run of `wese-trade-forward-4.2-a03e20f1d4` starts with
  `started_at` = the current UTC time. It is never backdated.
  - Symbols are checked against OKX (8 s budget).
  - When offline, the pre-registered universe is kept and noted on the run.
- **A local run is open:** it is resumed (cursors, open signals, no duplicates).

The temporary run from the build container (`docs/forward-testing.md` §13) is **not**
migrated and does not become the desktop run.

Signals are only observed while the app is running. After a restart, missed candles are
caught up for lifecycle only, never as new signals.

## 7. Updates

- Uses the official **Tauri 2 updater** (`tauri-plugin-updater`). The endpoint is
  `https://github.com/0xazzam-sy/Wese-Trade/releases/latest/download/latest.json`.
- Signature verification is always on and is never disabled.
- The **public** key is injected at release time from the repository variable
  `TAURI_UPDATER_PUBKEY`. The **private** key exists only as the secret
  `TAURI_SIGNING_PRIVATE_KEY` (+ `_PASSWORD`) and is never committed.
- Builds without a public key report «التحديثات غير مهيأة في هذا الإصدار».
- **UX** (Settings → التطبيق → «التحقق من التحديثات»):
  - shows the new version and release notes, with «تنزيل وتثبيت» or «لاحقاً»;
  - updates are never forced;
  - installing first downloads and **verifies** the signed package, then stops the backend
    gracefully (flush, cursors, DB closed), installs and relaunches;
  - the database in app-data is never touched by an update.

Create the key pair once, on your own machine:

```bash
cd desktop && npx tauri signer generate -w ~/.tauri/wese-trade.key
# secret   TAURI_SIGNING_PRIVATE_KEY          = contents of ~/.tauri/wese-trade.key
# secret   TAURI_SIGNING_PRIVATE_KEY_PASSWORD = the password you chose
# variable TAURI_UPDATER_PUBKEY               = contents of ~/.tauri/wese-trade.key.pub
```

Losing the private key means existing installations can no longer be updated
automatically. Keep it backed up.

## 8. GitHub: CI, releases, roles

GitHub holds source, CI/CD, release artifacts and history. It is **never** used for the
runtime database, logs or forward-test data.

| Workflow | Trigger | What it does |
| --- | --- | --- |
| `ci.yml` | push / PR | backend + frontend gates (ruff, mypy, pytest, eslint, prettier, tsc, vitest, build) |
| `desktop.yml` | push / PR (desktop, backend, frontend) | see the steps below |
| `release.yml` | tag `vX.Y.Z` | see the steps below |

`desktop.yml` runs on **windows-latest** and **macos-14** (Apple Silicon):

1. build the sidecar (self-tested) and the app;
2. **install** the NSIS installer silently on Windows, or use the `.app` on macOS;
3. run `scripts/desktop_smoke.py` against the **installed** app, with no Python or Node on
   `PATH`:
   - first launch: first admin and a new forward-test run;
   - relaunch: same user, same run;
   - checks the real native data paths;
   - checks a graceful stop and no orphan process after each launch;
4. run a second pass offline, with crash recovery, under a non-ASCII path containing spaces;
5. upload the installers and logs.

`release.yml`:

1. runs `desktop.yml`;
2. builds `WeseTrade_<v>_x64-setup.exe` + `.msi` (Windows) and `Wese Trade.app` + `.dmg`
   (macOS arm64), with signed updater artifacts;
3. creates a **draft** GitHub Release with `latest.json`.

Users receive the update only after a person publishes the draft.

Release steps:
1. Bump the version everywhere. A test enforces that these match:
   - `backend/app/__init__.py` and `backend/pyproject.toml`;
   - `frontend/package.json` and `desktop/package.json`;
   - `desktop/src-tauri/tauri.conf.json` and `Cargo.toml`.
2. Tag `vX.Y.Z` and push.
3. Review the draft release, then publish.

## 9. Code signing (not configured yet)

Builds are **unsigned** until certificates are provided. Nothing is faked.

- **Windows (Authenticode):**
  - Obtain an OV/EV code-signing certificate (or Azure Trusted Signing).
  - Configure `bundle.windows.signCommand` (e.g. `signtool sign /fd sha256 /tr <tsa> /td sha256 …`
    or `trusted-signing-cli …`) in a release config, with the credentials in GitHub secrets.
  - Unsigned installers show a SmartScreen warning ("More info → Run anyway").
- **macOS (Developer ID + notarization):**
  - Requires an Apple Developer account. Set the secrets `APPLE_CERTIFICATE` (base64
    .p12), `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`,
    `APPLE_PASSWORD` (app-specific) and `APPLE_TEAM_ID`.
  - Tauri then signs (including the bundled sidecar binaries) and notarizes.
  - Unsigned apps must be opened with right-click → Open the first time; a downloaded DMG
    may need `xattr -dr com.apple.quarantine "/Applications/Wese Trade.app"`.

## 10. Building

Prerequisites (developers only): Python 3.12, Node 22, Rust stable, and on Linux the WebKitGTK
4.1 development packages.

```bash
# 1) packaged backend sidecar + compiled UI (self-tests the result)
python -m pip install -r backend/requirements-build.txt
python scripts/build_sidecar.py

# 2) desktop app for the current OS (unsigned local build, no updater artifacts)
cd desktop && npm ci
npx tauri build --config '{"bundle":{"createUpdaterArtifacts":false}}'
#   Windows: --bundles nsis,msi      macOS: --bundles app,dmg

# 3) automated check of the result (first launch + relaunch, graceful stop, no orphan)
python scripts/desktop_smoke.py "<installed app executable>"
```

**Desktop development.** This uses the repo's Python backend, not a packaged sidecar.

- With Vite HMR:

  ```bash
  cd frontend && npm run dev                       # http://localhost:5173 (proxy → :8000)
  cd desktop && WESE_DESKTOP_DEV_PYTHON=../backend/.venv/bin/python \
    WESE_DESKTOP_DEV_BACKEND_DIR=../backend \
    WESE_DESKTOP_DEV_URL=http://localhost:5173 npx tauri dev
  ```

- Without HMR: set `WESE_DESKTOP_DEV_WEB_DIR=../frontend/dist` instead of
  `WESE_DESKTOP_DEV_URL`.

The browser workflow (`scripts/dev.sh`) is unchanged.

## 11. Troubleshooting

| Symptom | Where to look / what to do |
| --- | --- |
| «تعذر تشغيل خدمة Wese Trade المحلية» | Settings or the error page → «فتح السجلات». Read `logs/backend-stderr.log` and `logs/backend.log` |
| «فشل تحديث قاعدة البيانات» | The original DB was restored. A copy is in `backups/`. Send `backend.log` |
| «بيانات السوق غير متصلة» | No internet or OKX unreachable. The app keeps working with saved data and reconnects automatically |
| News / weather unavailable | The source is unreachable. The last cached headlines stay visible. Signals are never affected |
| App already running | Only one instance is allowed. Launching again focuses the existing window |
| Reset everything | Quit the app, then move the data root (§2) elsewhere. A new run starts on the next launch |
