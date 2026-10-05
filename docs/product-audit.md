# Wese Trade — Product Core Audit (Phase 4.2.5)

Audit date: 2026-10-05.

**Baseline before any change:**

- Backend: 298 tests passed; ruff and mypy clean (209 files).
- Frontend: 104 tests passed; tsc, eslint, prettier and build clean.
- Live OKX: 10 tests passed.

The "Action" column records what this phase did. ✅ = verified working; 🔧 = fixed or
completed in 4.2.5; 🗑 = removed.

| Feature | Status found | Implementation | Test coverage | Action |
| --- | --- | --- | --- | --- |
| Login / logout / session cookie | working | `auth/tokens.py` (JWT in httpOnly cookie), `/auth/login,logout,session,me` | backend + frontend tests | ✅ |
| Argon2 hashing + timing equalizer | working | `auth/passwords.py` | unit tests | ✅ |
| Login throttling | working | `auth/rate_limit.py` (per user + per address) | tests | ✅ |
| Roles admin / analyst / viewer | working (backend `require_roles`, frontend `ProtectedRoute`) | | tests | ✅ |
| First-run admin | **terminal only** (`create_admin`) | — | — | 🔧 UI first-run setup (`/auth/setup`), race-safe, only while zero users |
| User management | **terminal only** | — | — | 🔧 admin UI: list, create, enable/disable, role |
| SECRET_KEY | placeholder allowed in dev, rejected in production | `core/config.py` | tests | 🔧 runtime secret file (`secret_key`, 0600) generated when unset; never printed |
| OKX public market data | working (symbols, tickers, candles, mark, funding, OI, WS reconnect, gap recovery, stale, 10m synthetic) | `market_data/okx/*` | offline + 10 live tests | ✅ |
| BingX / Binance runtime | none in code | doc `bingx-market-data.md` only | — | 🗑 historical doc marked as superseded |
| Charts (2 panels) | working (independent stores, states) | `features/charts/*` | tests | ✅ + E2E browser check |
| Analysis engine | working (no-lookahead/no-repaint/replay tests) | `analysis/*` | extensive | ✅ unchanged |
| Signal engine / forward test | working | `signal_engine/*`, `forward_test/*` | tests | ✅ unchanged; 🔧 BUY/SELL/NEUTRAL real-engine fixtures |
| Timeframe policy | working | `validation.py`, forward-test ownership | tests | ✅ |
| News | **placeholder** (`news_provider_not_configured`) | `news/service.py` | — | 🔧 real Arabic RSS provider (display only, cached, sanitized, graceful failure) |
| Weather | **placeholder** (unconfigured provider) | `services/weather` | — | 🔧 real Open-Meteo via backend proxy, city chosen in settings, no fake values |
| Scanner | **placeholder** route `/scanner/status`, unused `scanner/contracts.py`, `scanner.update` event | | — | 🗑 removed (scanner is out of scope; not faked) |
| Market overview columns "الإشارة / الثقة" | **always "--"** | `MarketOverview.tsx` | — | 🗑 removed placeholder columns and chip |
| Settings page | **missing** (theme toggle only) | — | — | 🔧 `/settings`: theme, account, strategy, provider, forward test, weather city, users (admin), runtime/desktop |
| Offline / backend-down UX | partial (indicators only) | header indicators | — | 🔧 global banners «بيانات السوق غير متصلة» / «الخادم المحلي غير متاح» |
| Date / time | working (browser TZ clock; UTC internally) | `HeaderClock`, `lib/format` | tests | ✅ |
| DB migrations | 3 revisions, upgrade tested | `alembic/` | migration test | 🔧 + downgrade/upgrade round-trip, + users/forward-test FK and unique checks |
| Forward test | working | Phase 4.2 | 17 tests | ✅ version `wese-trade-forward-4.2-a03e20f1d4` unchanged |
| Backtests page | working (research view, admin/analyst) | `/backtests` | tests | ✅ |
