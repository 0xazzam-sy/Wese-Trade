# OKX market data

Wese Trade reads **public** OKX market data for USDT-settled perpetual swaps.

- **No credentials:** no API key, secret, passphrase, OKX login or account connection is
  needed or supported. No signature headers are ever sent.
- **No private API:** there are no account, trade, order, position or private WebSocket
  endpoints anywhere in the code.
- **Isolation:** everything OKX-specific lives in `backend/app/market_data/okx/`. The rest
  of the app talks to the exchange-agnostic `MarketDataProvider` protocol.

> **Data-source note.** Wese Trade analyzes **OKX** public perpetual swap data. You may
> execute trades manually on another exchange such as BingX. Prices can differ slightly
> across exchanges (independent order books, liquidity, microstructure). Any future signals
> are based on OKX market data, not on another exchange's execution price, and no automatic
> cross-exchange correction is attempted.

---

## 1. Endpoints

| | URL | Notes |
|---|---|---|
| REST | `https://openapi.okx.com` | Production REST host per the official docs (`OKX_REST_URL`) |
| Public WS | `wss://ws.okx.com/ws/v5/public` | Port **443** (`OKX_PUBLIC_WS_URL`) |
| Business WS | `wss://ws.okx.com/ws/v5/business` | Port **443**; candle channels live here (`OKX_BUSINESS_WS_URL`) |

The official docs still print WebSocket URLs with `:8443`. Wese Trade deliberately uses the
default TLS port **443**: 8443 is being discontinued (October 31, 2026), and from the
build environment it reset the connection.

**REST endpoints used** (all public; documented per-IP limits in brackets):

| Purpose | Endpoint |
|---|---|
| Instruments | `GET /api/v5/public/instruments?instType=SWAP` |
| Recent candles (latest 1440 rows, 300 per request) | `GET /api/v5/market/candles` [40 req / 2 s] |
| Older candles | `GET /api/v5/market/history-candles` [20 req / 2 s] |
| One ticker (best bid/ask fallback) | `GET /api/v5/market/ticker?instId=` |
| All tickers, bulk | `GET /api/v5/market/tickers?instType=SWAP` [20 req / 2 s] |
| Mark prices, bulk | `GET /api/v5/public/mark-price?instType=SWAP` |
| Funding, bulk (documented `instId=ANY`) | `GET /api/v5/public/funding-rate?instId=ANY` |
| Open interest | `GET /api/v5/public/open-interest?instType=SWAP&instId=` |
| Server time (connectivity checks) | `GET /api/v5/public/time` |

Envelope: `{"code": "0", "msg": "", "data": [...]}`. The code is a **string**, and anything
other than `"0"` is an error:
- `50011` / `50061` mean rate limited
- `51001` means unknown instrument
- `51000` means a bad parameter

## 2. Channel separation

| Socket | Channels | Feed |
|---|---|---|
| business | `candle1m`, `candle5m`, `candle15m`, `candle30m`, `candle1H` | **candles** (charts, gap recovery, stale detection) |
| public | `tickers` (last, bid, ask), `mark-price` | **quotes** (price headers, best bid/ask, mark) |

There are exactly **two shared connections** for the whole backend, never one per chart
or browser. Health tracks each feed separately:
- **Candle feed down:** charts show "reconnecting".
- **Only the quote feed down:** the overall state is `degraded` and charts stay live. The
  header price temporarily falls back to candle closes.

## 3. Heartbeat and subscription limits

- **Silence:** OKX closes a connection that receives no data for 30 s.
- **Ping:** after **20 s** of silence the client sends the text `ping` and expects `pong`.
- **Dead socket:** if nothing arrives within a further **10 s**, the socket is replaced.
- **Subscribe-request limit:** 480 subscribe/unsubscribe requests per connection per hour.
  The client keeps a registry of `(channel, instId)` pairs, so it handles that as follows:
  - Changes are **debounced** (150 ms) and **batched** (up to 50 args per request).
  - A net-zero burst (subscribe then unsubscribe) sends nothing.
  - Charts on the same symbol share one subscription, through reference counting in the
    subscription manager.
- **Connection limit:** 30 connections per channel; we use two connections in total.
- **Service notices:** an OKX `event: "notice"` (e.g. a planned upgrade) triggers a
  proactive reconnect.

## 4. Instruments and mapping

- **Selection:** `instType=SWAP`, `settleCcy=USDT`, `ctType=linear`, and `instId` ending in
  `-USDT-SWAP`. On 2026-10-04 that gave 485 live contracts out of 500 SWAP instruments; the
  15 coin-margined (inverse) swaps are excluded.
- **State:** `live` maps to active. `suspend`, `preopen` and `test` map to unavailable.
  A contract that disappears is marked delisted, live subscriptions are released, and
  clients are told.
- **Mapping:** `BTC-USDT-SWAP` ↔ `BTCUSDT`. Both are stored (`exchange_symbol`, `symbol`).
  The UI shows `BTCUSDT`; lookups also accept `BTC-USDT-SWAP`, `BTC-USDT` and `btc/usdt`.
- **Exact filters:**
  - `tick_size = tickSz`, `step_size = lotSz` and `min_quantity = minSz`, read from OKX
    (never derived from a precision).
  - Price and quantity precision are computed **from** those filters.
  - Sizes are in **contracts**. `contract_value = ctVal` in `ctValCcy`; for example, BTC is
    0.01 BTC per contract.
  - OKX publishes no minimum notional for swaps, so it is `null`.
  - Max leverage comes from `lever`.
- **Refresh:** every 20 minutes, and never hardcoded.

## 5. Candles

- **Row format:** `[ts, o, h, l, c, vol, volCcy, volCcyQuote, confirm]`, newest first.
  - `ts` is the UTC open time in ms.
  - `vol` is in contracts, `volCcy` in the **base** currency, `volCcyQuote` in USDT.
  - Wese Trade's `volume` is **`volCcy` (base)** and `quote_volume` is `volCcyQuote`.
- **Close flag:** `confirm` is `"0"` for a forming candle and `"1"` for a closed one. It is
  used directly; there is no time-based guessing. Closed candles are:
  - emitted **once**
  - never reopened by a later forming push
  - ignored on duplicate pushes

  If a newer candle arrives before the close push (rare), the older one is finalized by
  inference. Only such an inferred close may later be corrected by the authoritative
  `confirm=1` push or by REST.
- **Validation:** rows are bar-aligned, positive, OHLC-consistent, and have non-negative
  volume. Malformed rows are dropped and counted, never fixed. Duplicates by open time
  resolve with closed beating forming.
- **History:** pages backwards with `after` (records strictly older than the timestamp),
  300 rows per request. `/market/candles` reaches the latest 1440 rows; deeper pages
  continue on `/market/history-candles`.
  - Charts load **800** candles: 3 requests for native bars.
  - 10m needs 1602 5m candles: 6 + 1 requests.
  - `before=` pages for older history use `after = before`.

## 6. Interval mapping and 10m aggregation

| Wese Trade | OKX bar / channel |
|---|---|
| `1m` | `1m` / `candle1m` |
| `5m` | `5m` / `candle5m` |
| `10m` | — synthetic from `5m` |
| `15m` | `15m` / `candle15m` |
| `30m` | `30m` / `candle30m` |
| `1h` | `1H` / `candle1H` |

**10m aggregation** (`services/aggregation.py`, unchanged from Phase 2):
- **Alignment:** buckets align on **UTC epoch** boundaries: `open_ms − open_ms mod 600 000`,
  i.e. hh:00 … hh:50. Never array pairing.
- **Values:** open = first child open, high = max, low = min, close = second child close;
  volume, quote volume and trade count are summed.
- **Completeness:** a bucket is closed only with **both** 5m children present and closed.
  A past bucket with a missing child is dropped, never fabricated.
- **Live:** the bucket is seeded with the already-known first child and re-emitted on every
  5m update. When the bucket completes it is emitted **closed exactly once**; with OKX this
  happens as soon as the second child's `confirm=1` arrives.

## 7. Cache (in memory, replaceable)

| Data | Lifetime |
|---|---|
| Instruments | until the next refresh (20 min) |
| Bulk tickers | 5 s, single-flight |
| Bulk funding | 60 s, single-flight |
| Bulk mark prices | 10 s; the live `mark-price` channel is preferred when fresh |
| Open interest | 30 s per viewed symbol |
| Best bid/ask | live `tickers` channel when under 10 s old, else REST ticker (5 s cache) |
| Closed candles | per stream, up to 2000 (LRU of 64 streams) |
| Paged history (`before=`) | 300 s |

## 8. Stale detection, reconnect and gap recovery

- **Stale:** a subscribed candle stream is **stale** when either:
  - it has had no candle message for `MARKET_STALE_AFTER_SECONDS` (60 s) **while the
    symbol's quotes kept arriving** (the market is trading, so the candle feed is broken), or
  - it has been silent for 3× that (180 s) regardless.

  A quiet instrument with no quotes either is not flagged before then. Stale streams show
  "البيانات متأخرة" and make the overall state `degraded`.
- **Reconnect:** each socket reconnects independently with exponential backoff (1 → 30 s)
  and ±20 % jitter, then resubscribes everything in batched requests.
- **Gap recovery:** after a **business** (candle) socket reconnect, every active stream
  fetches its last 60 candles over REST and reconciles them:
  - deduplicated by symbol + timeframe + open time
  - the forming candle is restored and the 10m aggregator re-seeded
  - clients get `market.resync` and reload history

  A skipped bucket in the live stream triggers the same recovery. A **public** socket
  reconnect only resubscribes, since OKX sends fresh ticker snapshots.

## 9. Rate limiting

- **Client limits:** token bucket of 8 req/s (burst 8), at most 4 concurrent requests,
  10 s timeout.
- **Requests stay low:** bulk endpoints are used for tickers, funding and mark prices; open
  interest and the REST best bid/ask are fetched only for symbols being viewed.
- **Throttling:** HTTP 429 or codes `50011`/`50061` set a **shared cooldown** (`Retry-After`
  or at least 5 s) for all requests and surface as `503 market_data_rate_limited` with
  `Retry-After`. They are never retried in a tight loop.
- **Transient errors** (network, 5xx) get up to 3 attempts with exponential backoff and
  jitter.

## 10. Real validation (2026-10-04, Claude Code cloud environment)

All results below come from the **real OKX production API** (REST via `openapi.okx.com`,
WebSockets on port 443). The environment's network policy allowed OKX, and OKX did not
geo-restrict it.

- **Live test suite** (`pytest -m live`): 10 passed. It covers instruments, 800-candle
  history for 1m/5m/15m/30m/1h, deep 5m history across the `history-candles` boundary,
  10m from 5m, tickers, funding, mark price, open interest, best bid/ask, and both sockets
  streaming.
- **Symbols:** 485 active USDT swaps. BTCUSDT, ETHUSDT and SOLUSDT are present. BTC has
  `tickSz 0.1`, `lotSz 0.01`, `minSz 0.01`, `ctVal 0.01 BTC`.
- **History checks** for BTCUSDT 1m/5m/10m/15m/30m/1h, ETHUSDT 5m/15m and SOLUSDT 5m
  (800 candles each): all ordered, unique, UTC-aligned, contiguous, OHLC-valid,
  non-negative volume, and every candle closed except the last.
- **Exact comparison** with OKX's own REST data for the same UTC candles: 12/12 identical
  (open, high, low, close, base volume). That covered 3 closed candles each of BTCUSDT 1m,
  5m and 15m, and ETHUSDT 15m.
- **10m independent check:** 249 completed buckets aggregated independently from raw OKX
  5m candles (both children `confirm=1`): **0 mismatches**, no duplicates, all
  UTC-aligned.
- **Realtime 1m:** BTCUSDT 1m was observed over 94 s spanning two minute boundaries. There
  were 96 events, each candle was closed exactly once, and there were 0 violations (no
  update after close, no high/low regression, open stable). ETHUSDT 5m streamed
  simultaneously.
- **Realtime 10m:** the 06:40 bucket received 159 live updates with a constant open. It
  closed exactly once at the 06:50Z boundary, and its closed values equal the REST
  aggregation of its two confirmed 5m children. The 06:50 bucket then started forming.
- **Socket drops:**
  - **Business socket:** reconnecting → connected, candle subscriptions restored, resync sent.
  - **Public socket:** overall `degraded` while the charts stayed live, then quote
    subscriptions were restored.
- **70 s candle-feed outage:** the charts showed reconnecting. After reconnect, gap
  recovery filled the missed 06:50 and 06:51 candles: contiguous, no duplicates, and 7
  recovered candles matched OKX REST.
- **Browser (Chromium, real data):**
  - branding "Wese Trade"; header "النظام: متصل · بيانات السوق: متصلة"
  - chart 1 BTCUSDT 1m and chart 2 ETHUSDT 5m live, with the header price and 24h change
    updating
  - rapid symbol switching (BTC→ETH→SOL→BTC, three times) and timeframe switching
    (1m→5m→10m→15m→30m→1h→1m) left 0 stray events from unselected streams
  - no console errors or warnings
- **Not verified:** in the browser itself, the reconnect transitions were not triggered
  against real OKX, because the container has no tool to sever one process's sockets. The
  identical status and stream events were verified in-process against real OKX (above),
  and the UI handling of those events was browser-tested in Phase 2.

## 11. Known limitations

- 10m is synthetic (OKX has no 10m bar). The chart and backend treat it like any other
  timeframe.
- Quote volume is not provided for swap tickers and is never estimated. The market list
  orders by base volume × last price for liquidity ordering only.
- Index price is not shown: the index-tickers endpoint is not used in this phase.
- Open interest is fetched per viewed symbol and reported in all three OKX units
  (contracts, base, USD). Units are never mixed.
- Very illiquid contracts can be quiet. They are only flagged stale after 180 s with no
  quotes either.
- OKX availability depends on the user's location and OKX's terms.
