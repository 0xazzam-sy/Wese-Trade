# Wese Trade — Architecture

Wese Trade is a **local-first, analysis-only** crypto market platform. It never places
orders, never stores exchange trading keys, and never uses an LLM to make trading decisions.

This document describes the architecture (Phases 1–4) and the domain contracts that later
phases must follow. Signal-engine details: [`signal-engine.md`](signal-engine.md);
validation: [`backtesting.md`](backtesting.md).

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
│ market_data/ · analysis/ · signal_engine/ · backtesting/ · scanner/ · news/      │
└──────────────────────────────────────────────────────────────────────────────────┘
```

In development, Vite proxies `/api` (HTTP and WebSocket) to FastAPI so the browser sees a
single origin. In production, a reverse proxy (e.g. Caddy/Nginx) serves `frontend/dist`
and forwards `/api` to Uvicorn: the same topology, so no code changes are required.

### Backend layering rules

| Layer          | Responsibility                                   | May depend on                 |
| -------------- | ------------------------------------------------ | ----------------------------- |
| `api/`         | HTTP parsing, status codes, cookies              | `services`, `schemas`, `auth` |
| `services/`    | Domain logic (users, health, later: signals…)    | `models`, `db`, domain pkgs   |
| `models/`      | SQLAlchemy ORM tables                            | `db`                          |
| `schemas/`     | Pydantic request/response models                 | —                             |
| `market_data/` | Normalized types + `MarketDataProvider` protocol | —                             |
| `websocket/`   | Envelope, connection manager, `/ws` route        | `auth`, `core`                |

Exchange-specific code (OKX) lives behind `MarketDataProvider` and is **never** called
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

| Type                 | Direction | Phase | Purpose                                                                                                                                                   |
| -------------------- | --------- | ----- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `system.status`      | S → C     | 1     | Sent on connect (`state: "connected"`)                                                                                                                    |
| `system.heartbeat`   | S → C     | 1     | Keep-alive every `ws_heartbeat_seconds` (20s)                                                                                                             |
| `system.ping`        | C → S     | 1     | Client keep-alive (every 15s)                                                                                                                             |
| `system.pong`        | S → C     | 1     | Reply to ping                                                                                                                                             |
| `system.error`       | S → C     | 1     | Protocol errors (`invalid_message`, …)                                                                                                                    |
| `market.subscribe`   | C → S     | 2     | `{symbol, timeframe}`; ack `market.subscribed`                                                                                                            |
| `market.unsubscribe` | C → S     | 2     | Release a subscription (also on disconnect)                                                                                                               |
| `market.tick`        | S → C     | 2     | Latest price for subscribed symbols                                                                                                                       |
| `market.candle`      | S → C     | 2     | `{symbol, timeframe, candle:{time,o,h,l,c,v,is_closed}}`                                                                                                  |
| `market.stream`      | S → C     | 2     | Per stream: `live` / `stale` / `reconnecting` / `unavailable`                                                                                             |
| `market.resync`      | S → C     | 2     | History changed (gap recovery): refetch it                                                                                                                |
| `market.status`      | S → C     | 2     | Exchange feed: connected/connecting/reconnecting/degraded/disconnected                                                                                    |
| `analysis.update`    | S → C     | 3     | Market analysis for a subscribed stream: `kind: "full"` (subscribe, every candle close) or `"live"` (forming-candle fields, throttled)                    |
| `signal.developing`  | S → C     | 4     | Forming-candle evaluation (throttled; never a trade, may change until close)                                                                              |
| `signal.confirmed`   | S → C     | 4     | New signal confirmed at candle close (`{signal}` with frozen plan)                                                                                        |
| `signal.updated`     | S → C     | 4     | Closed-candle evaluation (`{evaluation}`), lifecycle change (`{signal}`), or full state on subscribe (`{evaluation, developing, active, last_confirmed}`) |
| `signal.closed`      | S → C     | 4     | Signal reached a final state (TP3, stop, invalidated, expired, closed)                                                                                    |
| `scanner.update`     | S → C     | 5     | Scanner row changes (not implemented)                                                                                                                     |

`signal.*` events carry `{symbol, timeframe, strategy, …}` (`strategy` = validation status
of the strategy version, Phase 4.1) and are sent only to connections
subscribed to that stream (via `market.subscribe`).

Close codes: `4401` unauthorized, `4403` session expired (client stops reconnecting and
returns to login), `1001` server shutdown. Any other close triggers exponential-backoff
reconnects (1s → 30s, ±20% jitter) on the client. The client also forces a reconnect if
nothing arrives for 45s.

---

## 4. Market data principles

- **Prices are `Decimal`** in the backend and **decimal strings** on the wire. They are converted
  to JS numbers only at the chart-rendering boundary.
- **Tick size, lot size and minimum size come from exchange filters** (OKX `tickSz`,
  `lotSz`, `minSz`), never derived from a precision and never hardcoded.
- **Market data source:** Wese Trade analyzes OKX data. Prices on other exchanges (where a
  user may trade manually) can differ slightly; future signals are based on OKX data.
- **All timestamps are UTC** internally and in storage. Candles are keyed by their UTC
  open time. The UI converts to the browser timezone for display only.
- Supported timeframes: `1m, 5m, 10m, 15m, 30m, 1h`.
  **OKX has no native 10m bar**: 10m candles are aggregated from 5m candles aligned
  to UTC epoch boundaries (`Timeframe.M10.aggregation_source`).
- Symbols are displayed as `BTCUSDT`. The provider maps them to exchange instrument ids
  (`BTC-USDT-SWAP`) and keeps both.
- Public market data needs no API keys. Wese Trade has no order or position endpoints.

### Phase 2 implementation (see `docs/okx-market-data.md` for OKX specifics)

```
OKX REST + 2 WS ─► okx/ (rest.py, stream.py, parser.py, provider.py)       exchange-specific
                   public socket: tickers, mark-price · business socket: candles
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

- Routes and the WebSocket talk only to `MarketDataEngine`/services, never to OKX.
- One shared exchange socket. App keys `(symbol, timeframe)` are reference-counted onto
  native exchange streams (10m → 5m), so the future scanner can reuse the same manager.
- Each browser connection has a bounded outbound queue and its own writer task, so a slow
  client never blocks the market feed.
- Frontend: `MarketFeed` routes events by `(symbol, timeframe)`. `ChartController` applies
  `series.update()` with ordering invariants. `useMarketChart` runs per chart with
  generation guards, so switching symbol or timeframe can never show stale candles.

### Phase 3 implementation: market intelligence (see `docs/market-intelligence.md`)

```
MarketDataEngine ──candle_listeners / resync_listeners──► analysis/service.py (AnalysisService)
                                                              │ one MarketAnalyzer per (symbol, timeframe),
                                                              │ seeded from 1000 candles, then +1 per close;
                                                              │ MTF context streams subscribed internally
                                                              ▼
                          analysis/engine.py  MarketAnalyzer.update(closed) / .snapshot(forming)
                            indicators/ · regime/ · structure/ · liquidity/ · zones/ · multi_timeframe/
                                                              ▼
           api/v1/endpoints/analysis.py (REST)        `analysis.update` via the app WebSocket
```

- `MarketAnalyzer` is the **single canonical implementation** shared by live analysis and
  (later) the scanner, backtester and signal engine. It is a deterministic streaming state
  machine: confirmed facts never repaint, and the forming candle only produces
  `developing` features (tested by the no-lookahead/replay suite).
- The engine never imports FastAPI or exchange code; the service never parses exchange
  formats. `news` is never imported by `analysis`.
- Output is **analysis only**: no labels, entries, stops, targets or confidence.

### Phase 4 implementation: signal engine (see `docs/signal-engine.md`)

```
AnalysisService ──AnalysisListener (on_seeded / on_closed / on_forming)──► SignalService
                                                                              │ waits for context TFs
                                                                              ▼ closing at the same instant
          runtime.evaluate_closed / evaluate_developing  ◄── also used by backtesting/runner.replay
                                   ▼
          SignalEngine.evaluate(SignalInput) -> SignalEvaluation     (pure, deterministic)
                                   ▼
          SignalTracker (dedupe, cooldown, fills, TP/SL, expiry)     (same in backtests)
                                   ▼
     signal.* events · signals / signal_outcomes · /api/v1/signals · /api/v1/backtests
```

- **Live == backtest.**
  - The engine and the tracker are the same objects in both.
  - The backtester replays candles sequentially. Context analyzers only see candles closed
    at or before the evaluated close.
  - Live waits up to 15 s for context candles closing at the same instant, so it sees the
    same inputs.
- **Versioned.** Every evaluation, signal and backtest run carries `strategy_version`
  (engine version + hash of signal and analysis configs).
- **Honest output.**
  - NEUTRAL is the default.
  - The score is confluence, not probability.
  - STRONG classes are disabled because evidence does not support them.
  - Validation results, including negative ones, are documented in `docs/backtesting.md`.
- The signal engine never imports FastAPI, exchange code or `news`.

---

## 5. Analysis pipeline

```
OKX public market data
  ↓
Market Data Provider          (REST history + WS stream; reconnect, rate limits)
  ↓
Normalizer                    (symbols, Decimal prices, UTC times, 10m aggregation)
  ↓
Candle Store / Live State     (closed candles persisted; forming candle in memory)
  ↓
Feature Calculation           (EMA, RSI, ATR, volume … streaming)        ✅ phase 3
  ↓
Market Regime                 (directional + volatility regime)          ✅ phase 3
  ↓
Structure Engine              (swing/internal pivots, BOS, CHoCH)        ✅ phase 3
  ↓
Liquidity Engine              (EQH/EQL, pools, sweeps)                   ✅ phase 3
  ↓
Zone Engine                   (order blocks, FVG, premium/discount, OTE) ✅ phase 3
  ↓
Multi-Timeframe Context       (higher-timeframe alignment)               ✅ phase 3
  ↓
Signal Scoring Engine         (setups → bull/bear confluence → class + trade plan)  ✅ phase 4
  ↓
Signal Lifecycle              (developing → confirmed → active → TP/SL/expired)     ✅ phase 4
  ↓
Backtester                    (same engine + tracker, fees/slippage, R metrics)     ✅ phase 4
  ↓
WebSocket / API               (signal.*, /signals, /backtests; scanner.update later)
  ↓
Frontend                      (display only)
```

### Shared strategy logic (live == backtest)

`SignalEngine.evaluate(SignalInput) -> SignalEvaluation` (`app/signal_engine/engine.py`) is a
**pure, deterministic function**: no network access, no wall-clock reads. Live
(`SignalService`), the backtester (`backtesting/runner.py`) and the future scanner call it
through `signal_engine/runtime.py` and share `SignalTracker`, so backtest results describe
the live behaviour (bar-level, see backtesting.md for the simulation assumptions).

### Signal labels

`STRONG_BUY`, `BUY`, `NEUTRAL`, `SELL`, `STRONG_SELL`

### Signal states

| State                | Meaning                                                                 |
| -------------------- | ----------------------------------------------------------------------- |
| `developing`         | Conditions forming on an open candle; may still change (never a trade)  |
| `confirmed`          | Conditions held at candle close; trade plan is frozen; awaiting fill    |
| `active`             | Entry filled                                                            |
| `tp1_hit`, `tp2_hit` | Partial targets reached                                                 |
| `tp3_hit`            | Final target reached (final)                                            |
| `stopped`            | Stop hit (final; same-candle stop+TP counts as stop, flagged ambiguous) |
| `invalidated`        | Close beyond the invalidation level before the fill (final)             |
| `expired`            | No fill within 6 candles (final)                                        |
| `closed`             | Time stop (48 candles) or opposite STRONG override (final)              |

### Signal strength score — important

«قوة الإشارة» such as **87/100** is a **strategy confluence score**: how many weighted
conditions of the strategy agree. It is **not** "an 87% probability that the trade wins" and
must never be presented that way in the UI, documentation, or API field descriptions.
Calibrated probabilities, if ever shown, require a separate backtest-validated statistic
with its sample size. The Phase 4 backtest found the score **uncalibrated** (holdout
expectancy fell as the score rose), so no probability is shown.

### News isolation

News is display-only. The `news` package must never be imported by `signal_engine`,
`scanner` or `backtesting`. Signals must be reproducible from market data alone.

### Phase 4.2 implementation: prospective forward test (see `docs/forward-testing.md`)

```
AnalysisService ──AnalysisListener──► ForwardTestService (owns 12 symbols × 15m/30m/1h)
                                         │ on_seeded: catch-up after cursor (lifecycle only)
                                         │ on_closed: open_time >= started_at, live, not stale
                                         ▼
          forward_test.evaluate_candle = gate + research_hypotheses + evaluate_hyps
                                         (the same functions as the Phase 4.1 simulator)
                                         ▼
          SignalTracker (frozen terms, paper fills, conservative same-candle ambiguity)
                                         ▼
     background writer → forward_test_* tables · /api/v1/forward-test · signal.* events
```

- **Ownership.**
  - `SignalService.excluded` is `forward_test.owns`, so the baseline never evaluates the
    streams the forward test owns.
  - `SignalService.delegate` routes `subscribe`/`current` for those streams to the forward
    test.
  - The baseline deployment is non-directional.
- **Immutability.**
  - The run stores its frozen config.
  - The service refuses to resume a run whose `strategy_version` differs from the code.
  - Only one open run per version is allowed (a partial unique index).
- **No tuning surface.** The API exposes reads plus admin pause, resume and stop.

### Phase 4.2.5 / 4.3: product completion and desktop runtime (see `docs/desktop.md`)

```
Tauri shell (Rust) ── free 127.0.0.1 port, app-data root, token ──► packaged sidecar
   │  splash/crash page (tauri://)            app/desktop.py: migrate(+backup) → uvicorn
   │  window → http://127.0.0.1:<port>/  ◄──── app/web.py: same-origin UI + CSP
   │  monitor (crash → Arabic crash page)      TrustedHost (loopback) + WS same-origin check
   └─ exit: POST /system/shutdown → bounded wait → kill;  stdin EOF = parent gone
```

- **Runtime paths.** One module, `app/core/runtime.py`, defines the development and desktop
  layouts. The shell resolves the native per-user app-data directory and passes it in.
- **Auth.**
  - First-run admin: `/auth/setup` works only while there are zero users.
  - Admin user management: `/users`.
  - The secret is per installation (`data/secret_key`).
- **News and weather.** Both are real and display only: Arabic RSS and Open-Meteo, proxied by
  the backend. An import-boundary test keeps them out of the signal, forward-test, analysis,
  research and backtesting code.
- **Removed placeholders.** The scanner status route, scanner contracts, the
  `scanner.update` event and the empty «الإشارة/الثقة» market-list columns are gone.

---

## 6. Database

Tables:

| Table                      | Since | Purpose                                                                                                                      |
| -------------------------- | ----- | ---------------------------------------------------------------------------------------------------------------------------- |
| `users`                    | 1     | `id, username, password_hash, role, is_active, created_at, updated_at, last_login_at`                                        |
| `signals`                  | 4     | Every confirmed signal: frozen plan/score/components/evidence, lifecycle state, `source` (live/backtest), `strategy_version` |
| `signal_outcomes`          | 4     | Exits, gross/net R, ambiguity, MFE/MAE per signal                                                                            |
| `backtest_runs`            | 4     | Config, data ranges, summary metrics, `strategy_version`                                                                     |
| `forward_test_runs`        | 4.2   | One prospective run: frozen config, `started_at`, status + history, symbols, timeframes, cost model, minimums                |
| `forward_test_signals`     | 4.2   | Confirmed forward-test signals: frozen terms (insert-once) + lifecycle                                                       |
| `forward_test_outcomes`    | 4.2   | Gross/net R, fees R, slippage R, holding bars, ambiguity per final signal                                                    |
| `forward_test_cursors`     | 4.2   | Last processed close per (run, symbol, timeframe): restart without replay                                                    |
| `forward_test_checkpoints` | 4.2   | Daily metric snapshots                                                                                                       |

All datetimes are timezone-aware UTC (`UTCDateTime` type).

Planned tables (not created yet):

| Table              | Purpose                                                            |
| ------------------ | ------------------------------------------------------------------ |
| `user_preferences` | Per-user layout, chart selections, theme (moves from localStorage) |
| `market_snapshots` | Persisted closed candles / symbol metadata for replay              |
| `news_cache`       | Fetched + translated headlines (display only)                      |

SQLite is used locally (`backend/data/wese_trade.db`). PostgreSQL only needs
`DATABASE_URL=postgresql+asyncpg://…` plus the `asyncpg` driver: models use portable types
(no native enums, explicit constraint naming, timezone-aware datetimes).

---

## 7. Frontend structure

```
src/
  app/          App root, router, query client
  layouts/      AppShell (realtime owner), AppHeader
  pages/        LoginPage, DashboardPage, BacktestsPage (admin/analyst), NotFoundPage
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
  `OverlayController` that diffs overlays by id. Phase 3 adds
  `features/analysis/overlays/AnalysisOverlay` (one v5 series primitive per chart: zones
  beneath candles, lines/labels above) drawing a pure `buildOverlayModel(snapshot, toggles)`:
  swing/internal pivots, BOS/CHoCH, protected levels, liquidity pools/EQH/EQL, sweeps, FVG,
  order blocks, premium/discount and OTE. Toggles persist in `wesetrade.overlays`.
  Overlays only draw backend-computed data. Phase 4 adds `signalOverlay(view, toggles)`:
  confirmed markers («شراء 78»), faded developing markers («شراء؟») and Entry/SL/TP1–3
  lines for the active signal only (toggles `signals`, `tradePlan`).
- **Analysis UI**: `MarketFeed` routes `analysis.update` per stream (and replays the latest
  analysis to a chart joining an existing stream); `useMarketChart` exposes it with the same
  generation guards as candles; `features/analysis/lib/merge.ts` applies live updates only
  on the matching full snapshot. The analysis panel (`features/signals/SignalPanel`) formats
  the nine analysis cells and the MTF block. A debug view exists only in development builds.
- **Signal UI (Phase 4)**:
  - `MarketFeed` routes `signal.*` per stream (cached and replayed to late subscribers).
  - `features/signals/lib/reduce.ts` applies events to a per-stream `SignalView`, and
    `display.ts` picks what to show: active > developing > last evaluation.
  - `SignalPanel` shows the class, «قوة الإشارة NN/100», the plan and the state.
    `SignalDetails` is the drawer.
  - `/backtests` (admin/analyst) reads `/api/v1/backtests`.
  - Signal colours come from the `--ns-sig-*` tokens.
- **Weather** is optional and isolated: provider interface + "not configured" provider.
  Location is requested only on explicit user action, with low accuracy.
