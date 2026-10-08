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

## 5. Stage A / B definitions (pre-registered 2026-10-08, before any Stage A/B result)

**Inputs.**

- Only the 5-second trade-flow buckets from the exchange trade archive (§2).
- Candles for 1m / 5m / 10m are built from the same buckets:
  - open = previous close; high / low / close = bucket extremes and last price;
  - volume = buy + sell notional.
- Market context comes from the Phase 7 `StateTracker`:
  - EMA 20 / 50 / 200;
  - ATR(14) and the ATR percentile;
  - structure input fixed at neutral (0).
- Volumes are in contract units × price. The per-symbol contract size is a constant scale, and
  every feature below is a ratio or a z-score, so the scale cancels.

**Decision points.** Every closed candle of the timeframe, per symbol. The first 300 candles of
the series are warm-up.

**Stage A features** (all causal; computed at the candle close `t`):

| id | feature | definition |
| --- | --- | --- |
| A1 | flow imbalance, 1 candle | (buy − sell) / (buy + sell) over the last candle |
| A2 | flow imbalance, 3 candles | same over the last 3 candles |
| A3 | net-flow z-score | net flow of the last candle ÷ the rolling std of per-candle net flow (last 288 candles) |
| A4 | large-trade imbalance | (big_buy − big_sell) / (buy + sell), last candle (big = ≥ previous day's p99 size) |
| A5 | absorption | A3 − (candle return ÷ rolling std of candle returns, 288): flow that price did not follow |
| A6 | flow acceleration | imbalance of the last 30 s − A1 |
| A7 | signed intensity | (trade count of the last candle ÷ its 288-candle mean) × sign(candle return) |
| A8 | BTC flow lead | A3 of BTCUSDT at the same close (alts only) |

**Targets.**

- Signed forward log-return over H = 1, 5, 10 and 30 minutes.
- The entry reference is the last price at **t + 20 s** (the manual-latency model).
- The latency-0 version is reported for decay.

**IC statistic.**

- Spearman rank correlation per symbol per UTC day.
- Overlapping horizons are thinned to non-overlapping samples (every max(H, TF)).
- The pooled t-statistic is mean(daily IC) / sd × √(symbol-days).
- Gate (§4): |t| ≥ 3 pooled, the same sign in ≥ 9 of 12 symbols, and the same sign in both
  development halves (before / after 2026-01-01).

**Stage B setups** (direction d = ±1; all evaluated on every timeframe):

| id | setup | condition at the candle close |
| --- | --- | --- |
| B-A | trend continuation | state UPTREND (DOWNTREND for d = −1); the candle's low (high) touched EMA20 ± 0.3 ATR; A3 ≥ +1.5 in d |
| B-B | breakout with aggression | close beyond the previous 20-candle high (low) by > 0.1 ATR; A3 ≥ 2 in d; A4 in d |
| B-C | liquidity sweep reversal | low (high) below (above) the previous 20-candle extreme; close back inside the extreme; A3 ≤ −1.5 against d (sellers absorbed at the low); close in the upper (lower) half of the candle |
| B-D | range-edge rejection | state RANGE; location in range ≤ 0.2 (≥ 0.8); A3 ≥ +1 in d |
| B-E | momentum impulse | the candle's \|return\| ≥ 1.5 ATR in d; A3 ≥ 2 in d; A7 ≥ 2 |

**Stage B statistic.**

- Mean signed forward return in bp, measured from the t + 20 s price, at H = 1 / 5 / 10 / 30 min.
- One event per symbol per setup and direction within H (no overlap).
- Also reported:
  - decay at +0 / +5 / +10 / +20 / +30 s;
  - per-symbol sign;
  - the two development halves;
  - n.
- Gate (§4): ≥ 9 bp at one H, ≥ 9 of 12 symbols positive, both halves positive, n ≥ 300.
- 9 bp is roughly the round-trip taker + slippage hurdle (≈ 14 bp) minus a maker-entry saving. A
  setup below that bar cannot pay costs after manual latency.

Only Stage B passes may proceed to Stage C (trade-plan construction).

## 6. Order-book subset (pre-registered 2026-10-08, before any order-book result)

**Cost and scope.**

- Reducing one day of L2 400-level updates costs ≈ 5 µs per line. That is 33 s for PEPE and
  several minutes for BTC / ETH.
- The order-book study therefore uses:
  - **6 symbols:** BTC, ETH, SOL, XRP, DOGE, PEPE;
  - **every second day** of the order-book development window (2026-06-10 → 07-31, 26 days).

**Features** (5-second state at the candle close; `app/research/micro/book.py`):

| id | feature |
| --- | --- |
| O1 | top-of-book size imbalance |
| O2 | top-5 imbalance |
| O3 | notional depth imbalance within 10 bp |
| O4 | notional depth imbalance within 25 bp |
| O5 | microprice − mid (bp) |
| O6 | spread (bp; context only) |

**Stage A gate for this subset.**

- The same IC statistic as §5, with targets measured from the +20 s price.
- Pass: |t| ≥ 3 pooled, the same sign in ≥ 5 of 6 symbols, and the same sign in both halves
  (before / after 2026-07-05).

## 7. Results (development segments only; validation and the holdout were not opened)

### 7.1 Data actually collected

| Source | Coverage | Quality |
| --- | --- | --- |
| Trade archive → 5 s flow buckets | 12 symbols × 367 archive days (2025-10-06 → 2026-10-07); **5,469,567,806 trades** | 0 duplicates, 0 out-of-order, 0 outside-day, 0 bad rows, 0 missing days |
| L2 400-level archive → 5 s book features | 6 symbols × 26 days (every 2nd day 2026-06-10 → 07-30); **811,906,650 book messages**; 14,976 snapshots | 0 crossed books, 0 out-of-order, every 5 s bucket filled |
| Live collector (prospective: trades-all, books5, OI, funding, liquidations) | Running since 2026-10-08 in an ephemeral container | Gaps (container restarts) are logged, not filled with invented data |

**Transient download failures.** 135 day files were marked missing when the container lost its
network. All of them were verified as available and re-ingested.

### 7.2 Stage A — feature signal (trade flow, 12 symbols, 177 days)

**Every trade-flow feature has a negative IC: aggressive flow mean-reverts.**

- This holds for A1, A2, A3, A5, A7 and A8, on every timeframe.
- Examples (+20 s latency):
  - 1m A2, H1: IC −0.014, t −23.6;
  - 5m A7, H5: IC −0.031, t −21.3;
  - 10m A2, H10: IC −0.032, t −17.2.
- Each is the same sign in 12 of 12 symbols and in both halves. The Stage A gate is passed with
  the *opposite* sign to every pre-registered setup.

**Order book (6 symbols, 26 days).**

- Passes:
  - O4 (25 bp depth imbalance), 10m, H10: IC +0.028, t 4.1, 6 of 6 symbols;
  - O2 / O3, 5m, H1.
- The O2 / O3 IC is **+0.047 / +0.038 at +0 s and flips to −0.020 at +20 s**. The top-of-book
  signal is consumed before a manual entry is possible.
- O6 (spread in bp) shows a large IC (+0.10 to +0.26). This is a **price-level artifact** (tick
  size ÷ price, ranked within the same day), not a directional signal. It was pre-registered as
  context only and excluded from the gate.

### 7.3 Stage B — setup directional edge (+20 s entry reference)

- 60 cells: 5 setups × 3 timeframes × 4 horizons.
- **One cell passed the bar: 5m B-E (momentum impulse), H5.**
  - n = 5,751; mean +11.0 bp; t 2.5.
  - Concentration check (Stage F rule, applied here):
    - **One day, 2025-10-10 (the liquidation crash), contributes +64,579 bp while the whole sample sums to +63,376 bp.**
    - Without it the mean is −0.2 bp; without the top 5 days it is −2.0 bp.
    - The median is −4.0 bp; 44% of trades are positive; the day-block 90% CI is −2.0 … +32.3 bp.
  - **Rejected: a single-event artifact.**
- Every other setup is below 9 bp, or fails the per-symbol or half-sample test. The best
  non-crash-driven means are around +2 to +4 bp.

### 7.4 Size of the real effects (diagnostic, development, crash day excluded)

**Fading extreme flow** (the direction Stage A supports), mean signed bp from the +20 s price:

| Timeframe | Fade signal | 5 min | 10 min | 30 min |
| --- | --- | --- | --- | --- |
| 1m | \|A3\| ≥ 3.5 | +0.7 | +1.2 | +1.4 |
| 5m | \|A3\| ≥ 3.5 | +0.6 | +1.3 | +0.9 |
| 10m | \|A3\| ≥ 3.5 | +1.7 | +2.4 | +2.2 |
| any | \|A7\| extremes | — | — | −5.5 to +2.0 |

- Medians are positive (+2 to +7 bp), but the continuation tails cancel them in the mean.

**Order-book depth imbalance:**

- |O4| ≥ 0.2: +0.3 to +0.8 bp.
- The rarer |O4| ≥ 0.4 cells are negative.

**Cost hurdle.**

- Round-trip taker + slippage ≈ 14 bp; maker / maker ≈ 4 bp before adverse selection.
- **No real microstructure effect reaches even the maker hurdle after manual latency.**

### 7.5 Verdict

- The microstructure data is real, complete and clean, and it **does contain statistically
  robust information**.
- Its tradable size after a 20 s manual-entry delay is **0–2.5 bp**, an order of magnitude
  below costs.
- The only information large enough to matter (top-of-book state) **decays and reverses within
  20 s**. It would require automated sub-second execution, which is outside the scope of a
  manual phone-trading product.
- OI and liquidation features have **no usable history**. They remain AWAITING PROSPECTIVE DATA
  (the collector is built and running).
- **Stages C–G were not run**, because no setup earned them. Validation and holdout segments
  remain sealed.

| Timeframe | READY | Blocker |
| --- | --- | --- |
| 1m | **NO** | NO EDGE (trade flow + order book tested); OI / liquidations: INSUFFICIENT MICROSTRUCTURE HISTORY |
| 5m | **NO** | NO EDGE (the only pass = a single crash day); OI / liquidations: INSUFFICIENT MICROSTRUCTURE HISTORY |
| 10m | **NO** | NO EDGE; OI / liquidations: INSUFFICIENT MICROSTRUCTURE HISTORY |
