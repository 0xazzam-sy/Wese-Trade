# Wese Trade — Product Core Audit (Phase 4.2.5)

Audit date: 2026-10-05.

**Baseline before any change:**

- Backend: 298 tests passed; ruff and mypy clean (209 files).
- Frontend: 104 tests passed; tsc, eslint, prettier and build clean.
- Live OKX: 10 tests passed.

The "Action" column records what this phase did. ✅ = verified working; 🔧 = fixed or
completed in 4.2.5; 🗑 = removed.

| Feature                                   | Status found                                                                                             | Implementation                                                             | Test coverage            | Action                                                                                                         |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- | ------------------------ | -------------------------------------------------------------------------------------------------------------- |
| Login / logout / session cookie           | working                                                                                                  | `auth/tokens.py` (JWT in httpOnly cookie), `/auth/login,logout,session,me` | backend + frontend tests | ✅                                                                                                             |
| Argon2 hashing + timing equalizer         | working                                                                                                  | `auth/passwords.py`                                                        | unit tests               | ✅                                                                                                             |
| Login throttling                          | working                                                                                                  | `auth/rate_limit.py` (per user + per address)                              | tests                    | ✅                                                                                                             |
| Roles admin / analyst / viewer            | working (backend `require_roles`, frontend `ProtectedRoute`)                                             |                                                                            | tests                    | ✅                                                                                                             |
| First-run admin                           | **terminal only** (`create_admin`)                                                                       | —                                                                          | —                        | 🔧 UI first-run setup (`/auth/setup`), race-safe, only while zero users                                        |
| User management                           | **terminal only**                                                                                        | —                                                                          | —                        | 🔧 admin UI: list, create, enable/disable, role                                                                |
| SECRET_KEY                                | placeholder allowed in dev, rejected in production                                                       | `core/config.py`                                                           | tests                    | 🔧 runtime secret file (`secret_key`, 0600) generated when unset; never printed                                |
| OKX public market data                    | working (symbols, tickers, candles, mark, funding, OI, WS reconnect, gap recovery, stale, 10m synthetic) | `market_data/okx/*`                                                        | offline + 10 live tests  | ✅                                                                                                             |
| BingX / Binance runtime                   | none in code                                                                                             | doc `bingx-market-data.md` only                                            | —                        | 🗑 historical doc marked as superseded                                                                          |
| Charts (2 panels)                         | working (independent stores, states)                                                                     | `features/charts/*`                                                        | tests                    | ✅ + E2E browser check                                                                                         |
| Analysis engine                           | working (no-lookahead/no-repaint/replay tests)                                                           | `analysis/*`                                                               | extensive                | ✅ unchanged                                                                                                   |
| Signal engine / forward test              | working                                                                                                  | `signal_engine/*`, `forward_test/*`                                        | tests                    | ✅ unchanged; 🔧 BUY/SELL/NEUTRAL real-engine fixtures                                                         |
| Timeframe policy                          | working                                                                                                  | `validation.py`, forward-test ownership                                    | tests                    | ✅                                                                                                             |
| News                                      | **placeholder** (`news_provider_not_configured`)                                                         | `news/service.py`                                                          | —                        | 🔧 real Arabic RSS provider (display only, cached, sanitized, graceful failure)                                |
| Weather                                   | **placeholder** (unconfigured provider)                                                                  | `services/weather`                                                         | —                        | 🔧 real Open-Meteo via backend proxy, city chosen in settings, no fake values                                  |
| Scanner                                   | **placeholder** route `/scanner/status`, unused `scanner/contracts.py`, `scanner.update` event           |                                                                            | —                        | 🗑 removed (scanner is out of scope; not faked)                                                                 |
| Market overview columns "الإشارة / الثقة" | **always "--"**                                                                                          | `MarketOverview.tsx`                                                       | —                        | 🗑 removed placeholder columns and chip                                                                         |
| Settings page                             | **missing** (theme toggle only)                                                                          | —                                                                          | —                        | 🔧 `/settings`: theme, account, strategy, provider, forward test, weather city, users (admin), runtime/desktop |
| Offline / backend-down UX                 | partial (indicators only)                                                                                | header indicators                                                          | —                        | 🔧 global banners «بيانات السوق غير متصلة» / «الخادم المحلي غير متاح»                                          |
| Date / time                               | working (browser TZ clock; UTC internally)                                                               | `HeaderClock`, `lib/format`                                                | tests                    | ✅                                                                                                             |
| DB migrations                             | 3 revisions, upgrade tested                                                                              | `alembic/`                                                                 | migration test           | 🔧 + downgrade/upgrade round-trip, + users/forward-test FK and unique checks                                   |
| Forward test                              | working                                                                                                  | Phase 4.2                                                                  | 17 tests                 | ✅ version `wese-trade-forward-4.2-a03e20f1d4` unchanged                                                       |
| Backtests page                            | working (research view, admin/analyst)                                                                   | `/backtests`                                                               | tests                    | ✅                                                                                                             |

## Verification performed

- **Browser E2E against real OKX** (Playwright/Chromium). The production React build was
  served by the packaged-style sidecar at `http://127.0.0.1:8130`.
  - **First run:** the setup screen appeared, the first admin was created from the UI, and the dashboard loaded.
  - **Market data:** OKX connected, symbols loaded, and both charts rendered.
  - **Analysis:** it reached the ready state.
  - **Timeframes:** switching to 5m showed «هذا الفريم غير مفعّل للإشارات حالياً»; 15m showed «اختبار مباشر».
  - **Independent charts:** chart 2 switched to SOLUSDT while chart 1 stayed on BTCUSDT.
  - **Pages:** `/forward-test` (stats + history) and `/settings` (fingerprint, users, theme) worked, and logout worked.
  - **After a graceful restart:**
    - invalid login was rejected and valid login worked (the user persisted);
    - the same forward-test run and its 36 cursors persisted, with no duplicates.
  - **Console errors:** 0 in the final run.
- **Bugs the E2E found and fixed:**
  - the same-origin WebSocket was rejected (403);
  - the CSP blocked the inline theme script;
  - DNS-rebinding exposure: there was no Host allowlist for the loopback service.
- **Real-candle signal fixtures** (`tests/signals/test_frozen_strategy_fixtures.py`):
  - the frozen strategy reproduces a real BUY (ETHUSDT 15m, 2026-09-18 05:00Z, score
    81.15, entry 2485.14, SL 2467.73, TP 2508.38 / 2518.31 / 2558.56);
  - it reproduces a real SELL (2026-07-31 12:00Z, score 79.2, entry 1876.0, SL 1889.13,
    TP 1857.96 / 1848.16 / 1835.03);
  - every other candle in those windows is NEUTRAL with a reason;
  - a stale feed or an inactive symbol turns the trigger candle NEUTRAL.
- **News and weather** were implemented against their documented formats and tested with
  recorded fixtures. Their hosts (`ar.cointelegraph.com`, `ar.beincrypto.com`,
  `api.open-meteo.com`) are **blocked by this build environment's network policy**, so the
  live E2E shows the honest states: «مصادر الأخبار غير متاحة حالياً» and a weather city
  prompt. They need a first live check on a normal internet connection.

## Phase 4.2.5 acceptance gate

| #     | Condition                                      | Result                                                                                                                            |
| ----- | ---------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| 1     | No critical TODO/FIXME in runtime code         | ✅ none found                                                                                                                     |
| 2     | No fake/mock market data in production runtime | ✅                                                                                                                                |
| 3     | No placeholder dashboard cards                 | ✅ scanner stub, «الإشارة/الثقة» columns removed; news/weather real                                                               |
| 4–6   | Login, users persist, roles                    | ✅ E2E + API tests (admin/analyst/viewer, 401/403)                                                                                |
| 7     | OKX works                                      | ✅ E2E + 22 live tests                                                                                                            |
| 8     | Both charts                                    | ✅ E2E (independent symbols/timeframes)                                                                                           |
| 9     | Analysis                                       | ✅ E2E ready state + analysis test suites                                                                                         |
| 10–12 | BUY / SELL / NEUTRAL                           | ✅ real-candle fixtures through the frozen evaluator                                                                              |
| 13    | Entry/SL/TP render                             | ✅ panel tests (BUY + forward SELL with the fixture's plan)                                                                       |
| 14    | Signal lifecycle                               | ✅ lifecycle + forward-test tests (fills, TP, stop, expiry, ambiguity, no duplicates)                                             |
| 15–16 | Forward test, restart                          | ✅ service tests + sidecar restart tests + E2E restart                                                                            |
| 17    | Strategy fingerprint unchanged                 | ✅ `wese-trade-forward-4.2-a03e20f1d4` (tests assert it)                                                                          |
| 18    | News real                                      | ✅ real RSS provider (live check pending: hosts blocked here)                                                                     |
| 19    | Weather real                                   | ✅ real Open-Meteo proxy (live check pending: host blocked here)                                                                  |
| 20    | Offline/disconnect UX                          | ✅ banners + offline sidecar startup test                                                                                         |
| 21    | Migrations                                     | ✅ fresh, existing (+backup), failure restore, downgrade/upgrade round trip                                                       |
| 22–24 | Tests, types, lint, build                      | ✅ backend 349 passed (ruff, mypy clean); frontend 126 passed (tsc, eslint, prettier, build clean)                                |
| 25    | Live OKX checks                                | ✅ 22 live tests; sidecar on real OKX evaluated exactly 12 × 15m candles at the 10:00Z close (all NEUTRAL with reasons), 0 errors |
| 26    | No Phase 5 code                                | ✅                                                                                                                                |

**PRODUCT CORE STATUS: READY FOR DESKTOP PACKAGING**
