# NeuralShot

A local-first, Arabic-first (RTL) platform for analysing BingX perpetual crypto futures
markets.

> **Analysis only.** NeuralShot never places orders, has no trading endpoints, and needs no
> exchange API keys.

**Current status: Phase 1 (foundation).** This phase includes:
- authentication and roles
- database and migrations
- the internal WebSocket
- the workstation UI shell (two charts, scanner, news and signal panels)
- dark and light themes

Market data, signals, scanner, news and backtesting are **not implemented yet**. Their
panels show explicit empty states. No fake data is shown anywhere.

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
│   │   ├── websocket/       Event envelope, connection manager, /ws endpoint
│   │   ├── market_data/     Normalized types + provider protocol (no BingX code yet)
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
│       ├── features/        auth, charts, scanner, news, signals, header, weather, realtime
│       ├── components/ui/   Design-system primitives
│       ├── stores/          Zustand stores
│       ├── services/        REST clients, WebSocket client, weather service
│       ├── types/           Wire/domain types
│       ├── lib/             env, http, formatting helpers
│       └── styles/          Design tokens (dark/light) + global CSS
├── docs/architecture.md     Architecture + future domain contracts
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
| `BINGX_BASE_URL`, `BINGX_WS_URL`, `NEWS_PROVIDER`, `NEWS_API_KEY` | no | Reserved for later phases |

**Frontend** (`frontend/.env.local`, optional):

| Variable               | Default                  | Notes                                 |
| ---------------------- | ------------------------ | ------------------------------------- |
| `VITE_API_BASE_URL`    | `/api/v1`                | Relative = same origin                |
| `VITE_WS_BASE_URL`     | *(derived from page)*    | e.g. `wss://example.com/api/v1`       |
| `VITE_DEV_BACKEND_URL` | `http://127.0.0.1:8000`  | Vite proxy target (dev only)          |

---

## Troubleshooting

- **Login says the server is unreachable**: make sure the backend (step 7) is running on
  port 8000.
- **`create_admin` says the database is not initialised**: run `alembic upgrade head` first.
- **Port 5173 is in use**: stop the other process. The dev server uses a fixed port because
  the backend's allowed origin depends on it.
