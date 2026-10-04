# NeuralShot

A local-first, Arabic-first (RTL) platform for analysing BingX perpetual crypto futures
markets.

> **Analysis only.** NeuralShot never places orders, has no trading endpoints, and needs no
> exchange API keys.

**Current status: Phase 2 (BingX market data).**

Phase 1 (foundation) provides:
- authentication and roles
- database and migrations
- the internal WebSocket
- the RTL workstation UI
- dark and light themes

Phase 2 adds real, read-only BingX perpetual futures data:
- the live symbol list
- historical and realtime candles on both charts for 1m, 5m, 10m (built from 5m), 15m,
  30m and 1h
- live prices and 24h change
- funding, open interest and best bid/ask
- a market overview list
- feed health, stale detection and gap recovery

Signals, the scanner, news and backtesting are **not implemented yet**. Their panels show
explicit placeholders ("--"), and no fake data is shown anywhere.

BingX details, assumptions and validation status are in
[`docs/bingx-market-data.md`](docs/bingx-market-data.md).

---

## Requirements

| Tool    | Version                      |
| ------- | ---------------------------- |
| Python  | 3.12 or newer                |
| Node.js | 20.19+ or 22.12+ (LTS)       |
| npm     | 10+ (bundled with Node.js)   |

---

## Setup (first time)

All commands start from the project root (the folder containing this README).

### 1. Clone / open the project

```bash
git clone <repository-url> neuralshot
cd neuralshot
```

### 2. Create the backend virtual environment

macOS / Linux:

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate
```

Windows (PowerShell):

```powershell
cd backend
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install backend requirements

```bash
pip install -r requirements-dev.txt
```

(`requirements.txt` holds runtime dependencies only. `requirements-dev.txt` adds tests and
linters.)

### 4. Create the backend configuration

macOS / Linux: `cp .env.example .env`
Windows: `Copy-Item .env.example .env`

Then generate a secret key and paste it into `SECRET_KEY=` in `backend/.env`:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

The placeholder key works for local development (a warning is logged). It is
**rejected when `APP_ENV=production`**.

### 5. Run the database migration

```bash
alembic upgrade head
```

This creates the SQLite database at `backend/data/neuralshot.db`.

### 6. Create the initial admin account

```bash
python -m app.scripts.create_admin
```

You will be prompted for a username and password (minimum 12 characters). There are no
default credentials. The command refuses to run if users already exist; use `--additional`
to add another admin. For scripted setups:

```bash
printf '%s' "$ADMIN_PASSWORD" | python -m app.scripts.create_admin --username admin --password-stdin
```

### 7. Start the backend (FastAPI)

```bash
python -m app.main
```

This serves on `http://127.0.0.1:8000` and auto-reloads in development. Leave it running.

### 8. Install frontend dependencies (new terminal)

```bash
cd frontend
npm install
```

Optional: `cp .env.example .env.local` to override defaults. Nothing needs changing
for local use.

### 9. Start the frontend (Vite)

```bash
npm run dev
```

### 10. Open the browser

Go to **http://localhost:5173** and sign in with the admin account from step 6.

### Start both at once (after setup)

macOS / Linux / Git Bash:

```bash
./scripts/dev.sh
```

---

## URLs and ports

| What                     | URL                                     |
| ------------------------ | --------------------------------------- |
| Web app                  | http://localhost:5173                   |
| API (direct)             | http://127.0.0.1:8000/api/v1            |
| Health check             | http://127.0.0.1:8000/api/v1/health     |
| Market feed health       | http://127.0.0.1:8000/api/v1/markets/health (logged in) |
| API docs (dev only)      | http://127.0.0.1:8000/api/docs          |
| WebSocket (via Vite)     | ws://localhost:5173/api/v1/ws           |

In development the Vite server proxies `/api` (HTTP and WebSocket) to the backend, so the
browser uses one origin and the secure httpOnly session cookie just works.

---

## Everyday commands

### Backend (inside `backend/` with the virtualenv active)

| Task                    | Command                                            |
| ----------------------- | -------------------------------------------------- |
| Run server              | `python -m app.main`                               |
| Apply migrations        | `alembic upgrade head`                             |
| New migration           | `alembic revision --autogenerate -m "describe"`    |
| Create admin            | `python -m app.scripts.create_admin`               |
| Tests                   | `pytest`                                           |
| Live BingX tests (internet) | `pytest -m live`                               |
| Lint                    | `ruff check .`                                     |
| Format                  | `ruff format .`                                    |
| Type-check (strict)     | `mypy app tests alembic`                           |

### Frontend (inside `frontend/`)

| Task              | Command                  |
| ----------------- | ------------------------ |
| Dev server        | `npm run dev`            |
| Production build  | `npm run build`          |
| Lint              | `npm run lint`           |
| Type-check        | `npm run typecheck`      |
| Format / check    | `npm run format` / `npm run format:check` |
| Tests             | `npm test`               |

### All quality gates

```bash
./scripts/check.sh
```

This runs backend ruff, mypy and pytest, then frontend eslint, prettier, tsc, vitest and the
build.

---

## Project structure

```
neuralshot/
├── backend/                 FastAPI service (Python 3.12)
│   ├── app/
│   │   ├── main.py          App factory + lifespan
│   │   ├── core/            Settings (.env), structured logging, app resources
│   │   ├── api/v1/          Versioned HTTP routes (thin) + dependencies
│   │   ├── auth/            Argon2 hashing, JWT cookie tokens, login throttling
│   │   ├── db/              Async SQLAlchemy engine/session, UTC datetime type
│   │   ├── models/          ORM models (users)
│   │   ├── schemas/         Pydantic request/response models
│   │   ├── services/        Domain logic (users, health)
│   │   ├── websocket/       Event envelope, per-client queues, /ws + market protocol
│   │   ├── market_data/     Models, provider protocol, bingx/ adapter, services/, engine
│   │   ├── signal_engine/   Contracts only (labels, states, Strategy protocol)
│   │   ├── backtesting/     Contracts only
│   │   ├── scanner/         Contracts only
│   │   ├── news/            Contracts + honest empty feed
│   │   ├── scripts/         create_admin CLI
│   │   └── utils/           UTC time helpers
│   ├── alembic/             Migrations
│   ├── tests/               pytest suite
│   └── data/                Local SQLite database (git-ignored)
├── frontend/                React + TypeScript + Vite + Tailwind
│   └── src/
│       ├── app/             Root component, router, query client
│       ├── layouts/         App shell + header
│       ├── pages/           Login, dashboard, 404
│       ├── features/        auth, charts, markets, news, signals, header, weather, realtime
│       ├── components/ui/   Design-system primitives
│       ├── stores/          Zustand stores
│       ├── services/        REST clients, WebSocket client + MarketFeed, weather service
│       ├── types/           Wire/domain types
│       ├── lib/             env, http, formatting helpers
│       └── styles/          Design tokens (dark/light) + global CSS
├── docs/architecture.md     Architecture + future domain contracts
├── docs/bingx-market-data.md  BingX API usage, assumptions, validation status
└── scripts/                 dev.sh (run both), check.sh (all quality gates)
```

For design decisions and the future analysis pipeline, see
[`docs/architecture.md`](docs/architecture.md).

---

## Configuration reference

**Backend** (`backend/.env`):

| Variable                      | Required | Notes                                        |
| ----------------------------- | -------- | -------------------------------------------- |
| `APP_NAME`                    | no       | Default `NeuralShot`                         |
| `APP_ENV`                     | no       | `development` / `test` / `production`        |
| `APP_HOST`, `APP_PORT`        | no       | Default `127.0.0.1:8000`                     |
| `DATABASE_URL`                | no       | Default SQLite in `backend/data/`            |
| `SECRET_KEY`                  | **yes**  | ≥ 32 chars; unique random value              |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | no       | Default 720 (12 h)                           |
| `FRONTEND_ORIGIN`             | no       | Comma-separated; used for CORS + WS origin   |
| `LOG_LEVEL`                   | no       | Default `INFO`                               |
| `MARKET_DATA_ENABLED`         | no       | Default `true`; `false` disables BingX entirely |
| `BINGX_BASE_URL`, `BINGX_WS_URL` | no    | Public BingX endpoints (no API keys needed) |
| `MARKET_STALE_AFTER_SECONDS`  | no       | Default 60; silence after which a stream is shown as stale |
| `NEWS_PROVIDER`, `NEWS_API_KEY` | no     | Reserved for later phases |

**Frontend** (`frontend/.env.local`, optional):

| Variable               | Default                  | Notes                                 |
| ---------------------- | ------------------------ | ------------------------------------- |
| `VITE_API_BASE_URL`    | `/api/v1`                | Relative = same origin                |
| `VITE_WS_BASE_URL`     | *(derived from page)*    | e.g. `wss://example.com/api/v1`       |
| `VITE_DEV_BACKEND_URL` | `http://127.0.0.1:8000`  | Vite proxy target (dev only)          |

---

## Troubleshooting

- **Charts say "جاري إعادة الاتصال بـ BingX..." / health shows `rest_reachable: false`**:
  the machine cannot reach `open-api.bingx.com` or `open-api-swap.bingx.com`. Check your
  internet, firewall or proxy. The app keeps running and recovers by itself once BingX is
  reachable.

- **Login says the server is unreachable**: make sure the backend (step 7) is running on
  port 8000.
- **`create_admin` says the database is not initialised**: run `alembic upgrade head` first.
- **Port 5173 is in use**: stop the other process. The dev server uses a fixed port because
  the backend's allowed origin depends on it.
