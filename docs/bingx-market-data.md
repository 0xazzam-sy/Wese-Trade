# BingX market data (Phase 2)

NeuralShot reads **public** BingX USDT-M perpetual futures market data. It needs no API
keys, has no account or trade endpoints, and never places orders. All BingX-specific code
lives in `backend/app/market_data/bingx/`. Nothing else knows BingX paths, symbol
spelling or message formats.

> **Verification status — read first.**
> This phase was built in a cloud container whose network policy **blocked**
> `open-api.bingx.com`, `open-api-swap.bingx.com` and `bingx-api.github.io`.
> - The API contract was taken from BingX's **official** documentation repository
>   (`github.com/BingX-API/BingX-swap-api-v2-doc`, last full revision 2023-04-17:
>   *Perpetual_Swap_API_Documentation.md* and *Perpetual_Swap_WebSocket_Market_Interface.md*).
>   The current docs site (`bingx-api.github.io/docs`) could not be fetched.
> - Items marked **[newer revision]** come from later API revisions. The code accepts
>   both forms defensively, but they were **not verified against the live API** here.
> - **No request was made to the real BingX API from this environment.** The live tests
>   (`pytest -m live`) exist for that purpose and must be run on a machine with
>   internet access (section 14).

---

## 1. REST endpoints used

Base URL: `https://open-api.bingx.com` (`BINGX_BASE_URL`). Every response uses the envelope
`{"code": 0, "msg": "", "data": ...}`. A non-zero `code` is an error. Decimal values are
returned as strings and parsed as `Decimal`.

| Purpose | Method + path | Params | Notes |
|---|---|---|---|
| Contract metadata | `GET /openApi/swap/v2/quote/contracts` | — | `symbol`, `asset`, `currency`, `pricePrecision`, `quantityPrecision`, `status` (1 online, 0 offline), `maxLongLeverage`/`maxShortLeverage`; **[newer revision]** `tradeMinQuantity`, `tradeMinUSDT`, `apiStateOpen` |
| Candles | `GET /openApi/swap/v3/quote/klines` | `symbol`, `interval`, `limit` (max **1440**), `endTime` | **[newer revision]** v3 path. If it answers HTTP 404 the client falls back once, permanently, to the documented `GET /openApi/swap/v2/quote/klines`. Rows: `{open, high, low, close, volume, time}`. The array-row form is also accepted defensively. |
| 24h tickers (bulk) | `GET /openApi/swap/v2/quote/ticker` | none → all symbols | `lastPrice`, `priceChange`, `priceChangePercent`, `openPrice`, `highPrice`, `lowPrice`, `volume`, `quoteVolume`, `closeTime`; **[newer revision]** `bidPrice`/`askPrice` (optional) |
| Mark/index price + funding (bulk) | `GET /openApi/swap/v2/quote/premiumIndex` | none → all symbols | `markPrice`, `indexPrice`, `lastFundingRate`, `nextFundingTime` (documented as "remaining ms", but the example shows an absolute epoch. Values > 10¹² are treated as absolute, otherwise as relative.) |
| Open interest | `GET /openApi/swap/v2/quote/openInterest` | `symbol` (required) | Per symbol only, so it is fetched only for a symbol whose details are being viewed |
| Best bid/ask | `GET /openApi/swap/v2/quote/depth` | `symbol`, `limit=5` | Best bid = max(bids), best ask = min(asks), spread = ask − bid |

Not used: account, trade, listen-key and other private endpoints.

## 2. WebSocket endpoint

`wss://open-api-swap.bingx.com/swap-market` (`BINGX_WS_URL`). There is **one shared
connection** for the whole backend, whatever the number of browsers or charts.

## 3. Subscription syntax

```json
{"id": "<uuid>", "reqType": "sub",   "dataType": "BTC-USDT@kline_5m"}
{"id": "<uuid>", "reqType": "unsub", "dataType": "BTC-USDT@kline_5m"}
```

The server acknowledges with `{"id": "...", "code": 0, "msg": ""}`. A non-zero code is
logged and recorded as a failed subscription.

Kline push:

```json
{"code": 0, "dataType": "BTC-USDT@kline_1m", "s": "BTC-USDT",
 "data": {"T": 1649832779999, "o": "...", "h": "...", "l": "...", "c": "...", "v": "..."}}
```

**[newer revision]** `data` may be a **list** of such objects. Both forms are parsed.
`T` is floored to the interval bucket. That yields the open time whether BingX sends the
bucket start (newer examples) or a time inside the bucket such as `xx:59.999` (older
examples).

Only kline streams are used. The latest price (`market.tick`) is derived from the kline
close of the streams already subscribed for the charts, so no extra per-symbol streams
are opened.

## 4. Heartbeat

The server sends `Ping` about every 5 s (compressed text). The client answers `Pong`
immediately. A JSON form `{"ping": ...}` is also answered with `{"pong": ...}`.
Protocol-level WebSocket pings are disabled because BingX uses this application-level
heartbeat.

**Dead-socket detection:** if *no frame at all* (pings included) arrives for **30 s**,
the socket is considered dead and replaced.

## 5. Compression

Every frame is **GZIP**-compressed. The decoder tries gzip, then zlib, then plain UTF-8, so
malformed or uncompressed frames are logged at DEBUG and counted instead of crashing the
loop.

## 6. Interval mapping

| NeuralShot | BingX | Native |
|---|---|---|
| `1m` | `1m` | yes |
| `5m` | `5m` | yes |
| `10m` | — | **synthetic, built from `5m`** |
| `15m` | `15m` | yes |
| `30m` | `30m` | yes |
| `1h` | `1h` | yes |

The backend owns this mapping (`Timeframe.source`). The frontend only ever sends `10m`.

## 7. 10-minute aggregation

Implemented in `services/aggregation.py`.

- **Buckets are aligned on UTC epoch boundaries:** `bucket = open_ms − (open_ms mod 600 000)`,
  which gives hh:00, hh:10 … hh:50. Children are grouped **by time**, never by array position.
- open = first child open; high = max of child highs; low = min of child lows; close = last
  child close; volume, quote volume and trade count are **sums**.
- **History:** a bucket is closed only if both 5m children exist, both are closed, and the
  bucket has ended. A *past* bucket with a missing child is **dropped**: it leaves a visible
  gap and is never fabricated. The current bucket is returned as forming (`is_closed=false`).
- **Live:** a `LiveAggregator` per symbol is seeded with the current bucket's already-known
  child (from history or REST), so a chart opened at xx:07 still shows the full 10m candle.
  Every 5m update re-emits the forming 10m candle. When the next bucket's first child
  arrives, the previous bucket is emitted **once** as closed, and only if both children
  were seen. Duplicate updates are ignored, and late updates for older buckets are left
  to REST reconciliation.
- History for 10m fetches `2 × limit + 2` 5m candles. For 1000 candles that is two requests
  (1440 + 562).

## 8. Symbol normalization

- `BTC-USDT` → `BTCUSDT` (dash removed, upper-cased). The exchange spelling is kept as
  `exchange_symbol` for API calls.
- Only USDT-settled contracts are kept (`symbol` ends with `-USDT` and `currency == USDT`).
- `status`: `1` → `active`, `0` → `unavailable`. A contract that **disappears** between
  refreshes becomes `delisted`. Its metadata is kept, live subscriptions to it are
  released, and subscribed clients receive `market.stream {state: "unavailable"}`.
  Already displayed candles stay on screen.
- **Tick size:** BingX publishes precision, not an explicit tick size, so
  `tick_size = 10^-pricePrecision` and `step_size = 10^-quantityPrecision`. Both are used
  for the chart's price scale.
- **No hardcoded symbol list.** The list is refreshed every **20 minutes**, retried every
  30 s until the first success. The default chart symbol is `BTCUSDT` if it is active,
  otherwise the first active symbol.

## 9. Caching (in-memory, replaceable)

`services/cache.py` defines a small `Cache` protocol plus `TTLCache`. Redis can replace it
later.

| Data | Lifetime |
|---|---|
| Contract metadata | until the next refresh (20 min) |
| Bulk 24h tickers | 5 s, single-flight (concurrent callers share one request) |
| Bulk funding / mark / index | 60 s, single-flight |
| Open interest | 30 s per symbol (viewed symbols only) |
| Best bid/ask | 5 s per symbol (viewed symbols only) |
| Closed candles | kept in the per-stream store (up to 2000 per stream, LRU of 64 streams) |
| Paged history (`before=`) | 300 s (it contains only closed candles) |
| Forming candle | live state only; dropped when the stream is released |

History for a subscribed, non-stale stream is served from memory when every needed closed
bucket is present. Otherwise it is fetched from REST and merged. Nothing is persisted to
the database in Phase 2.

## 10. Reconnection and gap recovery

- **Exchange socket:** backoff 1 s × 2ⁿ up to 60 s with ±20 % jitter. States are
  `connecting`, `connected`, `reconnecting` and `disconnected`, broadcast as `market.status`.
- **Resubscribe:** after every reconnect the full subscription registry is re-sent. The
  registry is a set, so subscriptions are never duplicated.
- **Gap recovery:** after a reconnect, each active stream fetches its last **60** candles
  over REST. Closed candles are reconciled (deduplicated by symbol + timeframe + open time)
  and the forming candle is restored. The 10m aggregator is re-seeded, and consumers get
  `market.resync`, which makes the browser reload that chart's history.
- **Live gaps:** if a push skips one or more buckets, the same recovery runs for that stream.
- **Finalization:** BingX kline pushes carry **no "final" flag**. A live candle is marked
  closed only when a newer candle arrives, or when REST returns it as completed. If a bucket
  ended more than 10 s ago and nothing newer arrived (a quiet market), REST is asked once to
  confirm. Closure is **never declared on a timer alone**.
- **Browser socket:** on reconnect the browser resubscribes and reloads history, so events
  missed while it was offline cannot leave silent gaps.

## 11. Rate-limit strategy

- The documented public limit is **20 requests/s per IP**. NeuralShot uses a token bucket
  of **8 req/s** (burst 8) and at most **4 concurrent** requests.
- Bulk endpoints are used wherever they exist (tickers, funding), so there are **no N+1
  requests**. Open interest and depth are fetched only for symbols being viewed.
- On **429**, **418** or business code **100410**, a shared cooldown pauses *all* requests
  (`Retry-After`, minimum 5 s). The request fails with `BingXRateLimited`, which the API
  maps to `503 market_data_rate_limited` plus `Retry-After`. It is **never retried in a
  tight loop**. The cooldowns are counted in `/markets/health` (`rate_limited_count`).
- Transient errors (network, timeout, 5xx) get up to 3 attempts with exponential backoff
  and jitter. Other 4xx responses and business errors are not retried.

## 12. Stale-data definition

A subscribed stream is **STALE** when the exchange socket is connected but no kline update
for it has arrived for **60 s** (`MARKET_STALE_AFTER_SECONDS`). Consumers receive
`market.stream {state: "stale"}`, the chart shows **"البيانات متأخرة"**, and the overall
feed state becomes `degraded`. The flag clears on the next update.

While the socket itself is down, streams report `reconnecting` instead. The UI never
labels data "live" without a live stream.

## 13. Known BingX limitations and assumptions

- There is no native 10m interval (handled by aggregation).
- There is no explicit tick size; it is derived from `pricePrecision`.
- There is no closed flag in kline pushes (handled by conservative finalization).
- `nextFundingTime` semantics are ambiguous in the docs (both forms are handled).
- Open interest is per symbol only (fetched on demand for viewed symbols).
- Very illiquid contracts can be legitimately quiet for over 60 s and will show as stale.
  That is honest (no new data arrived), but it is not an outage.
- The v3 klines path and the list form of kline pushes are **[newer revision]**
  assumptions, not verified here (see the top of this document).

## 14. Validation performed

**Automated (no network).** 91 backend tests run against official-doc example payloads and
fakes, plus 49 frontend tests. They cover:
- parsing and malformed data
- retries and rate limits
- gzip, Ping/Pong, resubscribe and silence detection
- 10m alignment, boundaries, missing children, duplicates and rollover
- live/REST merge, gap recovery, stale streams and delisting
- API/WS integration
- switching races in the frontend

**End-to-end against a BingX-protocol stand-in (2026-10-03/04).** Because the real exchange
was blocked, a local server speaking the same REST envelopes, gzip WS frames, Ping and sub
acks, fed with a **synthetic** price walk, drove the real `BingXProvider` code path in
Chromium. It is a test harness only and is not part of the repository.
- Both charts rendered history and live updates.
- All six timeframes loaded.
- Symbol search and switching worked.
- A dropped exchange socket led to reconnect, resubscribe and gap recovery.
- A paused feed was flagged stale (both charts showed "البيانات متأخرة") and recovered.
- A full exchange outage left the app up, failed the charts independently, and recovered
  them automatically.
- The browser console had no errors, apart from the expected 503 during the simulated outage.
- Backend 10m candles matched an independent aggregation of the source 5m data (0
  mismatches over 299 buckets). 1m/5m/15m/30m/1h matched the source with 0 mismatches,
  aligned and contiguous.

**Real BingX: NOT performed.** No BingX values were compared in this environment. To
validate on a machine with internet access:

```bash
cd backend && source .venv/bin/activate
pytest -m live -v           # real contracts, klines (all native intervals), 10m, tickers,
                            # funding, OI, depth, and a live kline stream
```

Then open the app and compare a few BTCUSDT 1m/5m/10m and ETHUSDT 15m OHLC values with
BingX's own chart for the same UTC minutes.

## 15. REAL EXCHANGE VALIDATION

### Attempt 1 — 2026-10-04 ~06:08 UTC — BLOCKED (not performed)

- **Environment:** Claude Code cloud container (Linux, Python 3.12, Node 22). Not the
  user's local machine. Outbound HTTPS goes through an egress proxy that enforces the
  environment's network policy.
- **DNS:** OK. `open-api.bingx.com` and `open-api-swap.bingx.com` both resolve to
  CloudFront addresses.
- **REST connectivity:** FAILED. The proxy rejects `CONNECT open-api.bingx.com:443` with
  **403** (policy denial). No TLS handshake with BingX took place, so this is not an SSL,
  certificate or URL problem.
- **WebSocket connectivity:** FAILED. Same 403 for `open-api-swap.bingx.com:443`.
- **`pytest -m live -v`:** 9/9 failed, all at the first network call with
  `BingXUnavailable: ... ProxyError: 403 Forbidden`. No BingX payload was received, so no
  conclusion about API behaviour, parsing, intervals, compression or heartbeat is possible.
- **Symbols, candle comparisons, 10m comparison, WebSocket, reconnect, ticker and browser
  validation:** **not performed**. They require real BingX data.
- **API assumptions corrected:** none (nothing could be observed).
- **Code changes:** none.

**To complete validation:**
- Allow `open-api.bingx.com` and `open-api-swap.bingx.com` in the cloud environment's
  network settings, **or**
- run on a machine with normal internet access:
  - `cd backend && pytest -m live -v`
  - then follow steps 3–13 of the Phase 2.5 validation plan (manual OHLC comparison,
    independent 10m check, realtime/rollover observation, switch races, reconnect, ticker
    check, browser check).

**Phase 2 remains NOT COMPLETE until this validation succeeds.**
