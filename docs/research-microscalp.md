# Wese Trade — Phase 8: MicroScalp (microstructure-aware lower-timeframe engine)

> **Status: DATA AUDIT + PRE-REGISTERED PROTOCOL.** This was written before any MicroScalp
> result.
>
> - Strategy 4.2 (15m/30m/1h) is unchanged.
> - No release happens in this phase. v1.0.1 stays production.
> - The rejected families (LTF-5.x, scalp-6 signals, fast-7) are not tuned further.
> - The scalp-6 analysis layer is kept as the **market-context layer**.

## 1. Data-source audit (probed 2026-10-08 against the live OKX public API; no credentials)

| Data | Live source | Historical source | History actually available | Verdict |
| --- | --- | --- | --- | --- |
| **Individual trades with aggressor side** | WS `trades` / `trades-all`; REST `market/trades` (last 500) | REST `market/history-trades` (≈ 3 months, 100 per request); **OKX historical-data archive, module 1, daily CSV** (`instrument_name, trade_id, side, price, size, created_time`) | **≥ 2 years** (files verified on 2024-10-01, 2025-04-01, 2025-10-01 and 2026-09-01). ETH ≈ 2.7 M trades/day, 16 MB/day zipped | **Retrospective validation possible** |
| **L2 order book (400 levels)** | WS `books` (400 levels, incremental), `books5` (snapshot), `bbo-tbt` | **Archive module 4** (daily tar.gz of L2 updates); module 5 = 5,000 levels; module 6 = tick-by-tick | **Rolling ≈ 4 months**: 2026-06-10 → today available, 2026-06-01 = 404. Very large: BTC 343 MB/day, ETH 467, ARB 298, SOL 188, DOGE 124, PEPE 53 | **Retrospective validation possible on a subset and the 4-month window only** |
| Open interest | REST `public/open-interest` (current); WS `open-interest` | REST `rubik/stat/contracts/open-interest-history` | The archive endpoint returns **zero-filled rows** for 5m history (verified). No usable OI history | **Prospective only** (collector) |
| Taker buy/sell volume (aggregated) | — | REST `rubik/stat/taker-volume-contract` | Zero-filled or "Not Found" for history (verified) | **Replaced by the trade archive** (exact aggressor flow) |
| Funding | WS `funding-rate`; REST current | REST `funding-rate-history` (≈ 3 months, already stored by Phase 4.1) | ≈ 3 months, 8-hourly | Context only: too slow for 1–10m decisions |
| Liquidations | WS `liquidation-orders` (all swaps) | REST `public/liquidation-orders` (latest ≈ 100 per underlying; hours) | **No history** | **Prospective only** (collector) |
| Market context (BTC/ETH impulse, relative strength) | candles + trades | candle store + trade archive | 1–2 years | Retrospective |

**Nothing is reconstructed from candles.** Aggressor flow comes only from the exchange's trade
`side` field. Order-book features come only from real L2 updates. OI and liquidation features
exist only once the prospective collector has gathered them.

## 2. Storage

- **Trade flow.** The trade archive is reduced to **5-second buckets** per symbol per day:
  - last / high / low trade price;
  - aggressive buy and sell volume;
  - buy and sell trade counts;
  - "large" buy and sell volume. A trade is large when its size ≥ the **previous day's** 99th
    percentile trade size, so the threshold is causal.
  - Files: `backend/data/research/micro/trades5s/<SYMBOL>/<YYYYMMDD>.bin` (fixed binary layout,
    ≈ 0.8 MB/day) plus a JSON quality record per day (trades, duplicates, ordering errors,
    first/last ts, p99).
  - Raw archives are downloaded, reduced and deleted.
- **The order book** gets the same treatment, as 5-second feature snapshots, built only from
  real L2 updates.
- **The live collector** (prospective data) writes its own rotating per-day files; nothing goes
  into the application database.

## 3. Splits

- **Trade flow (12 symbols, 1 year 2025-10-07 → 2026-10-07):** the same calendar splits as
  Phase 5–7:
  - development < 2026-04-01;
  - validation 2026-04-01 → 06-30;
  - **sealed holdout ≥ 2026-07-01**.
  - Readers refuse holdout dates unless they are explicitly unlocked.
- **Order book (≈ 4-month window):**
  - development 2026-06-10 → 07-31;
  - validation 08-01 → 08-31;
  - **sealed holdout 09-01 → 10-07**.
  - Disclosure: these calendar months overlap the OHLCV holdout that earlier *candle* families
    never read. They are used here only for this new information source.

## 4. Stages and gates (fixed now)

| Stage | Question | Pass bar (development unless stated) |
| --- | --- | --- |
| **A** feature signal | Does a causal microstructure feature predict the next 1 / 5 / 10 / 30 minutes of signed returns? | Spearman IC with \|t\| ≥ 3 pooled, the same sign in ≥ 9 of 12 symbols and in both halves of development |
| **B** setup directional edge | Does a setup (context × flow trigger) move price in its direction **after manual latency**? | Mean signed forward return, measured **from the price 20 s after the signal** (the manual-entry model), ≥ 9 bp at some horizon; ≥ 9 of 12 symbols positive; both halves positive; n ≥ 300 |
| **C** realistic plan | Entry / SL / TP1–3 with fees, spread, slippage, 5 / 10 / 20 / 30 s latency, limit fills and missed fills | — |
| **D** development | net E ≥ +0.03 R, PF ≥ 1.05, n ≥ 300, plateau over neighbours | |
| **E** validation | net E > 0, PF ≥ 1.05, n ≥ 100 | |
| **F** sealed holdout (once) | net E > 0, 90% day-block CI lower bound > −0.02 R, PF ≥ 1.10, n ≥ 100, concentration and direction checks (as in Phase 7) | |
| **G** prospective | Live collector plus a separate forward namespace before any production activation | |

- **Manual-execution constraint.** The signal fires at a candle close. The user's entry price
  is the last trade price at **+5 / +10 / +20 / +30 s**. Stage B uses +20 s.
- **Signal decay.** The edge is reported at each latency; a setup whose edge disappears by +20 s
  is rejected.
- **Costs.** Taker 0.05% + max(0.02%, 1 tick) slippage per market side. Limit entries pay the
  maker fee and fill only through the price.
- **Signal validity.** `valid_until` = the signal close + 1 candle (1m / 5m) or + ½ candle
  (10m). A plan whose entry was not possible within that window is `ENTRY MISSED`.
