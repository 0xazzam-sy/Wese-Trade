# Wese Trade

A local-first, Arabic-first (RTL) platform for analysing crypto perpetual swap markets,
using **OKX public market data**.

> **Analysis only.** Wese Trade never places orders and has no trading, account or
> position endpoints. Market data comes from OKX's **public** API: no API key, secret,
> passphrase, OKX login or account connection is needed.

> **Data source.** Wese Trade analyzes OKX USDT perpetual swap market data. You may
> execute trades manually on another exchange (for example BingX). Prices can differ
> slightly between exchanges (independent order books, liquidity and microstructure).
> Signals are computed from OKX data, not from another exchange's execution price.
> No automatic cross-exchange correction is attempted.

**Current status: Phase 4.2 — prospective forward test running (paper only).**

> **Read this before using signals.** Phase 4.1 walk-forward research found **no robust edge**.
>
> - 12 liquid OKX perpetuals, 3 chronological validation windows.
> - Baseline: −0.077 R per trade over 2,605 validation trades. No pre-registered candidate passed.
> - Details: [`docs/research.md`](docs/research.md).
>
> Phase 4.2 freezes **one** exploratory candidate as **`wese-trade-forward-4.2-a03e20f1d4`**
> (fingerprint `4.2-a03e20f`) and measures it on **new** candles only. It is shown as
> «اختبار مباشر»: «الإشارات قيد الاختبار وليست توصيات مضمونة.»
>
> - Directional signals only on 15m/30m/1h, from trend continuation only.
> - 1m, 5m and 10m: «هذا الفريم غير مفعّل للإشارات حالياً».
> - The Phase 4 baseline is shown as «غير مُثبت» and no longer emits BUY/SELL.
> - Protocol, criteria and run record: [`docs/forward-testing.md`](docs/forward-testing.md).

Phase 1 (foundation) provides:

- authentication and roles
- database and migrations
- the internal WebSocket
- the RTL workstation UI
- dark and light themes

Phase 2 adds real, read-only market data:

- the live list of all active OKX USDT perpetual swaps
- historical and realtime candles on both charts for 1m, 5m, 10m (built from 5m), 15m,
  30m and 1h
- live prices and 24h statistics
- best bid/ask, mark price, funding and open interest
- a market overview list
- feed health, stale detection, reconnect and gap recovery

Phase 3 adds the deterministic **market intelligence engine** (analysis only):

- trend (EMA 20/50/100/200 features), market regime, volatility (ATR + percentiles), RSI
  and momentum, volume features
- swing and internal structure: pivots, HH/HL/LH/LL, BOS, CHoCH, protected highs/lows
- liquidity: equal highs/lows, liquidity pools, sweeps (vs breakouts)
- fair value gaps, order blocks, premium/discount/equilibrium, OTE zone
- multi-timeframe context (e.g. 5m read against 15m and 1h)
- strict no-repaint / no-lookahead guarantees, with tests
- the analysis panel, an MTF panel and toggleable chart overlays

Phase 4 adds the **signal engine** (no trading, no leverage, no LLM):

- one deterministic engine shared by live evaluation and the backtester
- four setup families:
  - trend continuation
  - pullback continuation
  - breakout continuation
  - liquidity reversal
- independent bull/bear scores and penalties; classes شراء / بيع / محايد
- «قوة الإشارة NN/100» is a confluence score, never a probability
- structural trade plans: entry (market or zone), stop beyond structure with a fee-aware
  floor, structural TP1–3 with R:R
- signal lifecycle (developing, confirmed, active, TP1–3, stopped, invalidated, expired),
  with cooldown and dedupe
- WebSocket `signal.*` events, REST endpoints, and `signals` / `signal_outcomes` /
  `backtest_runs` tables
- the signal panel, a details drawer, chart markers, Entry/SL/TP lines, and an
  admin/analyst backtest view (`/backtests`)
- a backtester with fees, slippage, a 70/30 time split, and score calibration

Phase 4.2 adds the **prospective forward test** (no tuning, no trading):

- a frozen, hash-versioned candidate; signals only from candles that open after the
  run's `started_at` and close live; restart-safe cursors with no replay and no duplicates
- `forward_test_*` tables (runs, signals, outcomes, cursors, daily checkpoints), kept
  separate from research and baseline data
- net/gross expectancy, PF, drawdown, average/median R, and breakdowns by timeframe,
  symbol, regime, side and score bucket; pre-registered pass/fail criteria
  (≥ 150 closed trades and ≥ 30 days)
- a dashboard status card and an admin/analyst `/forward-test` page with history, filters
  and CSV/JSON export; admins can only pause, resume or stop

The scanner and news are **not implemented yet**. Their fields show explicit placeholders
("--"), and no fake data is shown anywhere.

Signal rules, scoring, trade plans and lifecycle:
[`docs/signal-engine.md`](docs/signal-engine.md). Backtest methodology and full results:
[`docs/backtesting.md`](docs/backtesting.md).

Analysis definitions, defaults, density checks and validation results are in
[`docs/market-intelligence.md`](docs/market-intelligence.md).

OKX endpoints, behaviour and the real-exchange validation results are in
[`docs/okx-market-data.md`](docs/okx-market-data.md).

---

## Requirements

| Tool    | Version                    |
| ------- | -------------------------- |
| Python  | 3.12 or newer              |
| Node.js | 20.19+ or 22.12+ (LTS)     |
| npm     | 10+ (bundled with Node.js) |

---

## Setup (first time)

All commands start from the project root (the folder containing this README).

### 1. Clone / open the project

```bash
git clone <repository-url> wese-trade
cd wese-trade
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

> **Keep `SECRET_KEY` secret.** It signs every login session: anyone who has it can forge a
> session for any user, including admins.
>
> - **Never commit it.** `backend/.env` is git-ignored; keep it that way, and never put the
>   key in `.env.example`, docs, screenshots, issues or chat.
> - **Never print or log it.** The app never logs it.
> - Use a **different** key per installation.
> - **If it leaks:** generate a new one and restart. All existing sessions become invalid
>   (users log in again).

The placeholder key works for local development (a warning that names the command above is
logged at startup). It is **rejected when `APP_ENV=production`**.

### 5. Run the database migration

```bash
alembic upgrade head
```

This creates the SQLite database at `backend/data/wese_trade.db`, including the Phase 4
`signals`, `signal_outcomes` and `backtest_runs` tables (migration `0002_signals`). Run it
again after every update.

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

| What                 | URL                                                                    |
| -------------------- | ---------------------------------------------------------------------- |
| Web app              | http://localhost:5173                                                  |
| API (direct)         | http://127.0.0.1:8000/api/v1                                           |
| Health check         | http://127.0.0.1:8000/api/v1/health                                    |
| Market feed health   | http://127.0.0.1:8000/api/v1/markets/health (logged in)                |
| Analysis snapshot    | http://127.0.0.1:8000/api/v1/analysis/BTCUSDT?timeframe=5m (logged in) |
| API docs (dev only)  | http://127.0.0.1:8000/api/docs                                         |
| WebSocket (via Vite) | ws://localhost:5173/api/v1/ws                                          |

In development the Vite server proxies `/api` (HTTP and WebSocket) to the backend, so the
browser uses one origin and the secure httpOnly session cookie just works.

---

## Everyday commands

### Backend (inside `backend/` with the virtualenv active)

| Task                                            | Command                                                                                     |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------- |
| Run server                                      | `python -m app.main`                                                                        |
| Apply migrations                                | `alembic upgrade head`                                                                      |
| New migration                                   | `alembic revision --autogenerate -m "describe"`                                             |
| Create admin                                    | `python -m app.scripts.create_admin`                                                        |
| Tests                                           | `pytest`                                                                                    |
| Live OKX tests (internet)                       | `pytest -m live`                                                                            |
| Live analysis tests (internet)                  | `pytest -m live_analysis`                                                                   |
| Download backtest history (internet, ~12 MB)    | `python -m app.scripts.fetch_history`                                                       |
| Run the backtest                                | `python -m app.scripts.run_backtest --name final --save-db`                                 |
| Research: choose universe + download (internet) | `python -m app.scripts.research_fetch --select` then `python -m app.scripts.research_fetch` |
| Research: walk-forward studies                  | `python -m app.scripts.run_research --name phase41`                                         |
| Research: Markdown report                       | `python -m app.scripts.research_report --name phase41`                                      |
| Lint                                            | `ruff check .`                                                                              |
| Format                                          | `ruff format .`                                                                             |
| Type-check (strict)                             | `mypy app tests alembic`                                                                    |

### Frontend (inside `frontend/`)

| Task             | Command                                   |
| ---------------- | ----------------------------------------- |
| Dev server       | `npm run dev`                             |
| Production build | `npm run build`                           |
| Lint             | `npm run lint`                            |
| Type-check       | `npm run typecheck`                       |
| Format / check   | `npm run format` / `npm run format:check` |
| Tests            | `npm test`                                |

### All quality gates

```bash
./scripts/check.sh
```

This runs backend ruff, mypy and pytest, then frontend eslint, prettier, tsc, vitest and the
build.

---

## Project structure

```
wese-trade/
├── backend/                 FastAPI service (Python 3.12)
│   ├── app/
│   │   ├── main.py          App factory + lifespan
│   │   ├── core/            Settings (.env), structured logging, app resources
│   │   ├── api/v1/          Versioned HTTP routes (thin) + dependencies
│   │   ├── auth/            Argon2 hashing, JWT cookie tokens, login throttling
│   │   ├── db/              Async SQLAlchemy engine/session, UTC datetime type
│   │   ├── models/          ORM models (users, signals, signal_outcomes, backtest_runs)
│   │   ├── schemas/         Pydantic request/response models
│   │   ├── services/        Domain logic (users, health)
│   │   ├── websocket/       Event envelope, per-client queues, /ws + market protocol
│   │   ├── market_data/     Models, provider protocol, okx/ adapter, services/, engine
│   │   ├── analysis/        Market intelligence engine (Phase 3) + live AnalysisService
│   │   ├── signal_engine/   Signal engine (Phase 4): rules, scoring, trade plan, lifecycle, live service
│   │   ├── backtesting/     History download, replay/simulate, metrics, reports
│   │   ├── research/        Phase 4.1: research store, universe, walk-forward studies
│   │   ├── scanner/         Contracts only
│   │   ├── news/            Contracts + honest empty feed
│   │   ├── scripts/         create_admin, fetch_history, run_backtest CLIs
│   │   └── utils/           UTC time helpers
│   ├── alembic/             Migrations
│   ├── tests/               pytest suite
│   └── data/                SQLite database, backtest history + reports (git-ignored)
├── frontend/                React + TypeScript + Vite + Tailwind
│   └── src/
│       ├── app/             Root component, router, query client
│       ├── layouts/         App shell + header
│       ├── pages/           Login, dashboard, backtests (admin/analyst), 404
│       ├── features/        auth, analysis, backtests, charts, markets, news, signals, header, weather, realtime
│       ├── components/ui/   Design-system primitives
│       ├── stores/          Zustand stores
│       ├── services/        REST clients, WebSocket client + MarketFeed, weather service
│       ├── types/           Wire/domain types
│       ├── lib/             env, http, formatting helpers
│       └── styles/          Design tokens (dark/light) + global CSS
├── docs/architecture.md     Architecture + future domain contracts
├── docs/okx-market-data.md    OKX API usage, behaviour, real validation results
├── docs/market-intelligence.md  Analysis definitions, no-repaint rules, defaults, validation
├── docs/signal-engine.md      Signal rules, scoring, trade plan, lifecycle, API/events
├── docs/backtesting.md        Backtest methodology and honest validation results (Phase 4)
├── docs/research.md           Phase 4.1 signal-edge research: walk-forward, robustness, verdict
├── docs/bingx-market-data.md  Historical: the former BingX provider (removed)
└── scripts/                 dev.sh (run both), check.sh (all quality gates)
```

For design decisions and the future analysis pipeline, see
[`docs/architecture.md`](docs/architecture.md).

---

## Configuration reference

**Backend** (`backend/.env`):

| Variable                        | Required | Notes                                                                  |
| ------------------------------- | -------- | ---------------------------------------------------------------------- |
| `APP_NAME`                      | no       | Default `Wese Trade`                                                   |
| `APP_ENV`                       | no       | `development` / `test` / `production`                                  |
| `APP_HOST`, `APP_PORT`          | no       | Default `127.0.0.1:8000`                                               |
| `DATABASE_URL`                  | no       | Default SQLite in `backend/data/`                                      |
| `SECRET_KEY`                    | **yes**  | ≥ 32 chars; unique random value. Never commit or share it (see step 4) |
| `ACCESS_TOKEN_EXPIRE_MINUTES`   | no       | Default 720 (12 h)                                                     |
| `FRONTEND_ORIGIN`               | no       | Comma-separated; used for CORS + WS origin                             |
| `LOG_LEVEL`                     | no       | Default `INFO`                                                         |
| `MARKET_DATA_ENABLED`           | no       | Default `true`; `false` disables market data entirely                  |
| `OKX_REST_URL`                  | no       | Default `https://openapi.okx.com`                                      |
| `OKX_PUBLIC_WS_URL`             | no       | Default `wss://ws.okx.com/ws/v5/public` (port 443)                     |
| `OKX_BUSINESS_WS_URL`           | no       | Default `wss://ws.okx.com/ws/v5/business` (candles)                    |
| `MARKET_STALE_AFTER_SECONDS`    | no       | Default 60; silence after which a stream is shown as stale             |
| `NEWS_PROVIDER`, `NEWS_API_KEY` | no       | Reserved for later phases                                              |

**Frontend** (`frontend/.env.local`, optional):

| Variable               | Default                 | Notes                           |
| ---------------------- | ----------------------- | ------------------------------- |
| `VITE_API_BASE_URL`    | `/api/v1`               | Relative = same origin          |
| `VITE_WS_BASE_URL`     | _(derived from page)_   | e.g. `wss://example.com/api/v1` |
| `VITE_DEV_BACKEND_URL` | `http://127.0.0.1:8000` | Vite proxy target (dev only)    |

---

## Troubleshooting

- **Charts say "جاري إعادة الاتصال بمزود البيانات..." / health shows `rest_reachable: false`**:
  the machine cannot reach `openapi.okx.com` or `ws.okx.com` (port 443). Check your
  internet, firewall or proxy, and that OKX is available in your location. The app keeps
  running and recovers by itself once OKX is reachable.
- **Upgrading from NeuralShot**: the default database file is now `backend/data/wese_trade.db`.
  To keep existing users, rename `backend/data/neuralshot.db` to `wese_trade.db` (or set
  `DATABASE_URL`). Everyone must sign in again once after the rename.
- **Analysis panel says "بيانات غير كافية للتحليل"**: the stream has fewer than 300 closed
  candles (e.g. a newly listed contract). Analysis needs EMA200 plus a warm-up period.
- **Login says the server is unreachable**: make sure the backend (step 7) is running on
  port 8000.
- **`create_admin` says the database is not initialised**: run `alembic upgrade head` first.
- **Port 5173 is in use**: stop the other process. The dev server uses a fixed port because
  the backend's allowed origin depends on it.
