# NeuralShot — Architecture

NeuralShot is a **local-first, analysis-only** crypto futures platform. It never places
orders, never stores exchange trading keys, and never uses an LLM to make trading decisions.

This document describes the Phase 1 foundation and the domain contracts that later phases
must follow.

---

## 1. System overview

```
┌──────────────────────── Browser (React SPA, RTL Arabic) ────────────────────────┐
│ pages/ → layouts/ → features/ (auth, charts, scanner, news, signals, …)         │
│ stores/ (Zustand UI state)   services/ (REST + WebSocket clients)                │
│ Displays data only — no trading logic in React.                                  │
└───────────────▲──────────────────────────────────────▲──────────────────────────┘
                │ REST /api/v1/* (httpOnly cookie)      │ WebSocket /api/v1/ws
┌───────────────┴──────────────────────────────────────┴──────────────────────────┐
│ FastAPI (backend/app)                                                            │
│ api/v1 (thin routes) → services/ (domain logic) → db/ + models/                  │
│ websocket/ (envelope, connection manager)                                        │
│ market_data/ · signal_engine/ · scanner/ · backtesting/ · news/  (contracts)     │
└──────────────────────────────────────────────────────────────────────────────────┘
```

In development, Vite proxies `/api` (HTTP and WebSocket) to FastAPI so the browser sees a
single origin. In production, a reverse proxy (e.g. Caddy/Nginx) serves `frontend/dist`
and forwards `/api` to Uvicorn: the same topology, so no code changes are required.

### Backend layering rules

| Layer          | Responsibility                                    | May depend on                 |
| -------------- | ------------------------------------------------- | ----------------------------- |
| `api/`         | HTTP parsing, status codes, cookies               | `services`, `schemas`, `auth` |
| `services/`    | Domain logic (users, health, later: signals…)     | `models`, `db`, domain pkgs   |
| `models/`      | SQLAlchemy ORM tables                             | `db`                          |
| `schemas/`     | Pydantic request/response models                  | —                             |
| `market_data/` | Normalized types + `MarketDataProvider` protocol  | —                             |
| `websocket/`   | Envelope, connection manager, `/ws` route         | `auth`, `core`                |

Exchange-specific code (BingX) will live behind `MarketDataProvider` and is **never** called
from route handlers directly.

---

## 2. Authentication & authorization

- Users are stored in the `users` table. Passwords are hashed with **Argon2id** (`argon2-cffi`).
- `POST /api/v1/auth/login` issues a signed JWT (HS256, `SECRET_KEY`) in an
  **httpOnly, SameSite=Strict** cookie (`ns_access`, path `/api/v1`, `Secure` in production).
  The token is never exposed to JavaScript.
- `GET /api/v1/auth/session` bootstraps the SPA (always 200). `GET /api/v1/auth/me` is a
  strict protected endpoint (401 without a session).
- Every request re-loads the user, so deactivating an account takes effect immediately.
- Login is throttled per username and per client IP (in-memory; swap for Redis when scaling out).
- Roles: `admin`, `analyst`, `viewer`. Route guards use `Depends(require_roles(...))` on the
  backend and `<ProtectedRoute roles=[...]>` on the frontend.
- The initial admin is created with `python -m app.scripts.create_admin`. There are no default
  credentials.

Planned: a `sessions` table for server-side revocation / "log out everywhere".

---

## 3. Internal WebSocket

Endpoint: `ws(s)://<host>/api/v1/ws`. Authenticated with the same cookie; the `Origin` header
must match `FRONTEND_ORIGIN`.

### Envelope (stable contract)

```json
{ "type": "system.status", "timestamp": "2026-10-03T12:00:00Z", "data": {} }
```

`timestamp` is always UTC ISO-8601. Clients send the same shape (`timestamp` optional).

### Event types

| Type               | Direction | Phase | Purpose                                         |
| ------------------ | --------- | ----- | ----------------------------------------------- |
| `system.status`    | S → C     | 1     | Sent on connect (`state: "connected"`)          |
| `system.heartbeat` | S → C     | 1     | Keep-alive every `ws_heartbeat_seconds` (20s)   |
| `system.ping`      | C → S     | 1     | Client keep-alive (every 15s)                   |
| `system.pong`      | S → C     | 1     | Reply to ping                                   |
| `system.error`     | S → C     | 1     | Protocol errors (`invalid_message`, …)          |
| `market.subscribe` | C → S     | 2     | `{symbol, timeframe}`; ack `market.subscribed`  |
| `market.unsubscribe` | C → S   | 2     | Release a subscription (also on disconnect)     |
| `market.tick`      | S → C     | 2     | Latest price for subscribed symbols             |
| `market.candle`    | S → C     | 2     | `{symbol, timeframe, candle:{time,o,h,l,c,v,is_closed}}` |
| `market.stream`    | S → C     | 2     | Per stream: `live` / `stale` / `reconnecting` / `unavailable` |
| `market.resync`    | S → C     | 2     | History changed (gap recovery): refetch it      |
| `market.status`    | S → C     | 2     | Exchange feed: connected/connecting/reconnecting/degraded/disconnected |
| `signal.live`      | S → C     | 3     | Developing signal (may change until close)      |
| `signal.confirmed` | S → C     | 3     | Signal confirmed at candle close                |
| `scanner.update`   | S → C     | 3     | Scanner row changes                             |

Close codes: `4401` unauthorized, `4403` session expired (client stops reconnecting and
returns to login), `1001` server shutdown. Any other close triggers exponential-backoff
reconnects (1s → 30s, ±20% jitter) on the client. The client also forces a reconnect if
nothing arrives for 45s.

---

## 4. Market data principles

- **Prices are `Decimal`** in the backend and **decimal strings** on the wire. They are converted
  to JS numbers only at the chart-rendering boundary.
- **Tick size and precision come from exchange metadata** (`MarketSymbol`), never hardcoded.
- **All timestamps are UTC** internally and in storage. Candles are keyed by their UTC
  open time. The UI converts to the browser timezone for display only.
- Supported timeframes: `1m, 5m, 10m, 15m, 30m, 1h`.
  **BingX has no native 10m interval**: 10m candles must be aggregated from 5m candles aligned
  to UTC epoch boundaries (`Timeframe.M10.aggregation_source`).
- Symbols are displayed as `BTCUSDT`. The provider maps them to exchange-native names
  (`BTC-USDT`).
- Public market data needs no API keys. NeuralShot has no order or position endpoints.

### Phase 2 implementation (see `docs/bingx-market-data.md` for BingX specifics)

```
BingX REST + WS ─► bingx/ (rest.py, stream.py, parser.py, provider.py)    exchange-specific
                      │  MarketDataProvider protocol (provider.py)
                      ▼
               services/  symbol_service · ticker_service · candle_service
                          aggregation (10m) · subscription_manager · cache · health
                      ▼
               engine.py  MarketDataEngine: live state, ref-counted subscriptions,
                          stale detection, finalization, gap recovery
                      ▼
      api/v1/endpoints/markets.py (REST)     websocket/market.py + ConnectionManager (WS)
```

- Routes and the WebSocket talk only to `MarketDataEngine`/services, never to BingX.
- One shared exchange socket. App keys `(symbol, timeframe)` are reference-counted onto
  native exchange streams (10m → 5m), so the future scanner can reuse the same manager.
- Each browser connection has a bounded outbound queue and its own writer task, so a slow
  client never blocks the market feed.
- Frontend: `MarketFeed` routes events by `(symbol, timeframe)`. `ChartController` applies
  `series.update()` with ordering invariants. `useMarketChart` runs per chart with
  generation guards, so switching symbol or timeframe can never show stale candles.

---

## 5. Future analysis pipeline

```
BingX
  ↓
Market Data Provider          (REST history + WS stream; reconnect, rate limits)
  ↓
Normalizer                    (symbols, Decimal prices, UTC times, 10m aggregation)
  ↓
Candle Store / Live State     (closed candles persisted; forming candle in memory)
  ↓
Feature Calculation           (EMA, RSI, ATR, volume profiles … pure functions)
  ↓
Market Regime                 (trending / ranging / volatile classification)
  ↓
Structure Engine              (swings, BOS, CHoCH)
  ↓
Liquidity Engine              (equal highs/lows, sweeps, liquidity levels)
  ↓
Zone Engine                   (order blocks, fair value gaps)
  ↓
Momentum / Volume / Volatility
  ↓
Multi-Timeframe Context       (higher-timeframe bias and confluence)
  ↓
Signal Scoring Engine         (confluence → label + confidence + trade plan)
  ↓
Signal Lifecycle              (developing → confirmed → closed / invalidated)
  ↓
WebSocket / API               (signal.live, signal.confirmed, scanner.update)
  ↓
Frontend                      (display only)
```

### Shared strategy logic (live == backtest)

`app/signal_engine/contracts.py` defines `Strategy.evaluate(MarketContext) -> Signal | None`.
A strategy is a **pure, deterministic function**: no network access, no wall-clock reads.
The live engine and the backtester both call the **same** `Strategy` implementation, so
backtest results describe the live behaviour exactly.

### Signal labels

`STRONG_BUY`, `BUY`, `NEUTRAL`, `SELL`, `STRONG_SELL`

### Signal states

| State         | Meaning                                                       |
| ------------- | ------------------------------------------------------------- |
| `developing`  | Conditions forming on an open candle; may still change        |
| `confirmed`   | Conditions held at candle close; trade plan is fixed          |
| `invalidated` | Setup broke before entry (e.g. structure violated)            |
| `closed`      | Plan finished: TP3, SL, or expiry. Outcome recorded           |

### Confidence score — important

A confidence score such as **87/100** is a **strategy confluence score**: how many weighted
conditions of the strategy agree. It is **not** "an 87% probability that the trade wins" and
must never be presented that way in the UI, documentation, or API field descriptions.
Calibrated probabilities, if ever shown, require a separate backtest-validated statistic
with its sample size.

### News isolation

News is display-only. The `news` package must never be imported by `signal_engine`,
`scanner` or `backtesting`. Signals must be reproducible from market data alone.

---

## 6. Database

Phase 1 table: `users` (`id, username, password_hash, role, is_active, created_at,
updated_at, last_login_at`). All datetimes are timezone-aware UTC (`UTCDateTime` type).

Planned tables (not created yet):

| Table              | Purpose                                                        |
| ------------------ | -------------------------------------------------------------- |
| `user_preferences` | Per-user layout, chart selections, theme (moves from localStorage) |
| `signals`          | Every generated signal with strategy version and inputs hash   |
| `signal_outcomes`  | Realized result per signal (hit TP1/2/3, SL, expired; R)       |
| `market_snapshots` | Persisted closed candles / symbol metadata for replay          |
| `backtest_runs`    | Parameters, strategy version, metrics, status                  |
| `news_cache`       | Fetched + translated headlines (display only)                  |

SQLite is used locally (`backend/data/neuralshot.db`). PostgreSQL only needs
`DATABASE_URL=postgresql+asyncpg://…` plus the `asyncpg` driver: models use portable types
(no native enums, explicit constraint naming, timezone-aware datetimes).

---

## 7. Frontend structure

```
src/
  app/          App root, router, query client
  layouts/      AppShell (realtime owner), AppHeader
  pages/        LoginPage, DashboardPage, NotFoundPage
  features/     auth · charts · scanner · news · signals · header · weather · realtime · system
  components/ui Design-system primitives (Panel, Button, SegmentedControl, …)
  stores/       Zustand: auth, theme, layout, chart selection, connection
  services/     api/* REST clients, realtime/RealtimeClient, weather/
  types/        Wire types mirroring backend schemas
  lib/          env, http (ApiError), formatting
  styles/       tokens.css (design tokens: dark default + light), global.css
```

- **Design tokens**: every color is a CSS variable in `styles/tokens.css`, mapped into
  Tailwind utilities (`bg-surface`, `text-fg-muted`, `text-bull`, …). Components never use
  raw hex values. The chart theme adapter reads the same variables at runtime.
- **RTL**: `<html dir="rtl" lang="ar">`. Layout uses logical properties (`ms-`, `pe-`,
  `start-`). Latin financial tokens (BTCUSDT, TP, SL, R:R, prices) use `.ns-ltr` / `.ns-num`
  bidi isolation. Charts are rendered LTR by convention.
- **Charts**: `CandlestickChart` is a presentation-only wrapper around lightweight-charts v5
  (`createChart`, `chart.addSeries(CandlestickSeries)`). Chart state (symbol/timeframe)
  lives in `chartStore`. Data comes from `useChartData`, which reports `unavailable` until
  phase 2.
- **Overlays**: `features/charts/overlays` defines the `ChartOverlay` contract and an
  `OverlayController` that diffs overlays by id. `SeriesPrimitiveOverlay` adapts v5 series
  primitives (`series.attachPrimitive`). Planned overlays include markers
  (`createSeriesMarkers`), order blocks, FVGs, BOS/CHoCH, liquidity levels, and Entry/SL/TP
  price lines. Overlays only draw backend-computed data.
- **Weather** is optional and isolated: provider interface + "not configured" provider.
  Location is requested only on explicit user action, with low accuracy.
