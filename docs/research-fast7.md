# Wese Trade — Phase 7: hierarchical fast-trading engine (`wese-trade-fast-7`) — 1m / 5m / 10m

> **Status: PRE-REGISTERED PROTOCOL**, written and committed before any Phase 7 result.
>
> - Strategy 4.2 (15m/30m/1h) is unchanged.
> - No release happens in this phase. v1.0.1 stays production.
> - The scalp-6 *analysis layer* (EMA, S/R strength, liquidity, structure, regime, direction) is
>   kept and reused. Its BUY/SELL decision model is rejected (`docs/research-scalp6.md`).
> - The Phase 5 holdout (2026-07-01 → 2026-10-07) is **still sealed** and stays sealed until a
>   candidate is frozen.

## 1. Decision hierarchy

`MARKET STATE → DIRECTION → LOCATION → SETUP → TRIGGER → TRADE PLAN`

Nothing below a level is evaluated unless the level above allows it.

1. **Market state:** UPTREND / DOWNTREND / RANGE / COMPRESSION / EXPANSION / TRANSITION.
   - Inputs: EMA ordering and slope, swing structure, ADX(14), the trailing range width over 60
     candles in ATR units, the Bollinger-width percentile and the ATR percentile.
   - Exact rules are in `backend/app/fast7/state.py`, fixed with this file.
2. **Direction:** BULLISH / BEARISH / NEUTRAL. It reuses the scalp-6 direction blend (EMA,
   structure, momentum, higher timeframe). HTF disagreement lowers confidence and is never a hard
   gate.
3. **Location:**
   - support / resistance (with strength) and the dynamic EMA zone;
   - range edges (top / bottom 20% of the trailing range), the breakout level and retest zone;
   - liquidity pools, and premium / discount of the trailing range.
   - A BUY needs room: no medium/strong resistance within 1 R above. SELL is the mirror.
4. **Setup modules**, each active only in its states:

| Module | Active states | Setup (long; short mirrored) | Trigger (one, strongest suitable) |
| --- | --- | --- | --- |
| M1 trend pullback | UPTREND | pullback into the EMA mid zone or a medium+ support, within 5 candles | micro-BOS: close > high of the last 3 candles |
| M2 breakout + retest | COMPRESSION → EXPANSION, UPTREND | decisive close above a medium+ level within the last 20 candles, then price back to within 0.3 ATR of it | retest close back above the level |
| M3 momentum expansion | COMPRESSION (≤ 10 candles ago) | expansion candle: range ≥ 1.5 ATR, close in the outer 20%, relative volume ≥ 1.5 | that candle's close |
| M4 liquidity sweep reversal | RANGE, TRANSITION, at a medium+ level or range edge | sweep of a pool or level (wick through, close back) | close back inside + candle direction |
| M5 range edge reversal | RANGE | price in the bottom 20% of the 60-candle range, at a support | rejection candle (lower wick ≥ 50% of range) |
| M6 extension mean reversion (new architecture) | any except EXPANSION | close ≥ 3 ATR from the EMA mid (z-extreme) | reversal candle closing back toward the mean |
| M7 session opening range (new architecture) | any | 30-minute opening range at 07:00 (London) and 13:30 (New York) UTC | first close beyond the opening range |
| M0 time-series momentum (baseline) | any | sign of the 20-candle return | every 20 candles |

## 2. Stage 1: market-behaviour screen (plan-independent, development data only)

- For every causal module event, on each TF (1m / 5m / 10m) and all 12 symbols, measure the
  **signed forward return** from the trigger close to the close `h` candles later, for
  h ∈ {5, 15, 30, 60}.
- Also measure the 30-candle maximum favourable / adverse excursion.
- The result is in basis points (bp) of price. Nothing depends on stops or targets.
- **Cost hurdles (round trip):**
  - taker = 2 × (0.05% + 0.02%) = **14 bp**;
  - maker-assisted (maker entry + maker take-profit, taker stop) = **≈ 6 bp** blended.
    This is an optimistic lower bound; real fills are modelled in Stage 2.
- **A module × TF passes the screen** only if, at some horizon h:
  1. the mean signed forward return ≥ **1.5 × the maker-assisted hurdle (9 bp)**;
  2. the mean is > 0 for ≥ 9 of the 12 symbols (where n ≥ 30);
  3. the mean is > 0 in **both halves** of the development period;
  4. n ≥ 300 events.
- Many module × TF × horizon combinations are scanned. The strict 1.5× bar and the
  symbol/time consistency requirements limit false discoveries.

## 3. Stage 2: trade-plan simulation (only for modules that pass Stage 1)

- **Plans:** structural stop (setup invalidation + 0.2 ATR); TP1 / TP2 / TP3 from S/R,
  liquidity, swings, a measured move or an ATR projection (the scalp-6 target engine).
- **Entries:**
  - market entry;
  - **maker-assisted** entry: a resting limit at the setup level, filled only *through* the
    price, expiring after a fixed number of candles, with no fallback chase. Adverse selection
    is captured because fills happen when price trades against the order. Missed entries are
    counted.
- **Lifecycle:** ACTIVE / TP1 / TP2 / TP3 / STOPPED / EXPIRED / ENTRY MISSED.
- **Anti-overtrading:** one live signal per symbol and timeframe. A new signal needs a new
  setup event (new structure, level interaction, breakout or sweep), never a repeat of the same
  move.
- **Selection.** A small set of plan variants per surviving module is chosen on development
  only: entry market/maker × target model structural/projection × break-even after TP1. The
  rule is the best net E with ≥ 300 trades and a plateau over neighbours.

## 4. Gates for production (unchanged in spirit from Phase 6; fixed now)

| # | Gate | Threshold |
| --- | --- | --- |
| G1 | Development | net E ≥ +0.03 R, PF ≥ 1.05, ≥ 300 trades |
| G2 | Validation | net E > 0, PF ≥ 1.05, ≥ 100 trades |
| G3 | Holdout | net E > 0 and 90% day-block bootstrap CI lower bound > −0.02 R; ≥ 100 trades |
| G4 | Holdout PF | ≥ 1.10 |
| G5 | Walk-forward | positive in ≥ 3 of the available quarterly folds |
| G6 | Drawdown | holdout max DD ≤ max(20 R, 0.25 R × trades) |
| G7 | Concentration | holdout E > 0 without the best 2 symbols; ≥ 50% of symbols (n ≥ 10) with E ≥ 0 |
| G8 | Cost stress | holdout net E > −0.02 R under high costs |
| G11 | Direction | BUY and SELL each > −0.05 R on holdout |
| G12 | Integrity | no-lookahead / no-repaint tests pass |

- **Stop rule.** If no module passes Stage 1, or no Stage 2 candidate passes G1, the phase ends
  with the documented proof that none of these architectures provides a usable edge after
  realistic costs on 1m/5m/10m.
- Nothing is released in that case.

---

## 5. Addendum (pre-registered before it was run): M8 cross-asset lead-lag

Every module above uses single-symbol price/volume information. M8 uses different information.

- **Event.** On a closed candle, BTC's candle return ≥ 2 × BTC ATR in the direction `d`, while
  the altcoin's same-candle return is < 0.5 × its own ATR in that direction (the alt is
  lagging).
- **Signal.** Trade the alt in direction `d`.
- **Scope.** 11 altcoins (BTC excluded); 1m and 5m; horizons h ∈ {1, 3, 5, 15} candles.
- **Screen.** Same bar as §2: mean ≥ 9 bp, ≥ 9 of 11 symbols positive, both halves positive,
  n ≥ 300.
- **Practicality note.** Lead-lag on crypto is typically arbitraged within seconds. Even a
  positive 1m result would be hard to execute manually from a phone; this is reported either
  way.

## 6. Stage 1 results (development data only; commit of this section)

| TF | M0 | M1 | M2 | M3 | M4 | M5 | M6 | M7 | M8 (lead-lag) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1m | fail | fail | fail | fail | fail | fail | fail | fail | fail (best +0.6 bp) |
| 5m | fail | fail | fail | fail | fail | fail | fail | fail | **PASS** at h = 5 (+9.51 bp, 9/11 symbols, halves +6.85 / +12.15, n = 1,653) |
| 10m | fail | fail | fail | fail | fail | fail | fail | fail | not run (5m-native study) |

**M1–M7 and M0.** All within about ±5 bp at every horizon on every timeframe (best +4.5 bp,
M4 10m h30), while typical 30-candle excursions are 45 bp (1m), 115 bp (5m) and 165 bp (10m).

**Exploratory observation, not pre-registered.** Session opening-range breakouts (M7)
fail consistently: −8 bp, with only 1 of 12 symbols positive, on 5m h60 and 10m h30. Fading
them would still fall short of the 9 bp bar. This is recorded, not pursued.

## 7. Stage 2 pre-registration for M8 (5m), written before simulation

- **Plans** (2 × 2 = 4 variants):
  - **V1:** stop = entry ∓ 1.5 ATR(alt); TP1 / TP2 / TP3 = 1 R / 2 R / 3 R (ATR projection);
    time stop 5 candles (the measured horizon).
  - **V2:** structural stop = the extreme of the last 3 alt candles ∓ 0.2 ATR (minimum
    0.5 ATR); TP1 / TP2 / TP3 = 1 R / 2 R / 3 R; time stop 15 candles.
  - **Entry:** market at the trigger close (taker) · **maker limit** at close ∓ 0.25 ATR (fills
    only *through* the price, expires after 3 candles, cancelled if TP1 or the stop trades
    first). This captures adverse selection; missed entries count as no trade.
- **Costs:** base for decisions, high for stress (§3 of Phase 6).
- **Overlap:** one position per alt at a time.
- **Selection:** best development net E with ≥ 300 trades whose neighbours (the other entry and
  the other plan) are both > 0. Then validation (G2), walk-forward (G5), and the sealed holdout
  once (G3–G11).

## 8. Stage 2 results: M8 lead-lag 5m (development only)

| Variant | Trades | Win | Gross | After fees | **Net** | Net (high) | PF | Max DD | /day | Missed | 90% CI (net) | L / S |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| V1 market | 1,545 | 41.9% | +0.073 | −0.126 | **−0.229** | −0.397 | 0.60 | 362 R | 2.9 | 34 | −0.301 … −0.152 | −0.28 / −0.15 |
| V1 limit (maker) | 1,202 | 42.1% | +0.002 | −0.163 | **−0.231** | −0.372 | 0.62 | 284 R | 2.2 | 400 | −0.315 … −0.142 | −0.29 / −0.15 |
| V2 market | 1,418 | 38.8% | +0.051 | −0.160 | **−0.276** | −0.468 | 0.61 | 393 R | 2.6 | 164 | −0.348 … −0.198 | −0.31 / −0.23 |
| V2 limit (maker) | 1,063 | 37.6% | −0.028 | −0.208 | **−0.291** | −0.460 | 0.60 | 313 R | 2.0 | 540 | −0.371 … −0.208 | −0.28 / −0.31 |

Every one of the 11 altcoins is negative under every variant (V1 market: −0.05 … −0.40 R).

**Why.** The +9.5 bp drift is only ≈ +0.07 R gross against a structural stop. Friction at
BTC-impulse moments is about 0.3 R: these are fast markets, so stop exits pay taker fees plus
slippage. The **maker-assisted entries show adverse selection** exactly as modelled: the limit
order fills precisely when the alt does *not* follow BTC, so gross falls from +0.073 to +0.002.
G1 fails, and validation and the holdout were not read.

## 9. Verdict: stop rule B (several fundamentally different architectures exhausted)

No 1m / 5m / 10m architecture produces a usable edge after realistic manual-execution costs. All
evidence below is on development data. The **holdout (2026-07-01 → 2026-10-07) has never been
read by any phase.**

| Phase | Architecture | Information used | Result |
| --- | --- | --- | --- |
| 5 | LTF-5.0 HTF-aligned pullback | price / EMA / swings | G1 fail on 1m, 5m, 10m (best −0.064 / −0.071 / −0.077 R) |
| 5 | LTF-5.1 trend + volatility-expansion | + regime gate | G1 fail (best −0.023 R on 10m; the 1m pocket has n = 58) |
| 6 | scalp-6 A trend continuation (confluence) | EMA, S/R strength, liquidity, structure, momentum, volume, HTF | G1 fail (best −0.085 R, 10m) |
| 6 | scalp-6 B momentum breakout | same | G1 fail (best −0.153 R) |
| 6 | scalp-6 C liquidity sweep reversal | same | G1 fail (best −0.141 R) |
| 6 | scalp-6 D regime-adaptive | same | G1 fail (best −0.089 R) |
| 7 | M1 state-gated trend pullback | + market state (ADX, BB width, range) | screen fail: ≤ ±4 bp forward drift |
| 7 | M2 breakout + retest | same | screen fail |
| 7 | M3 momentum expansion after compression | same | screen fail |
| 7 | M4 liquidity sweep at a level / range edge | same | screen fail (best +4.5 bp) |
| 7 | M5 range edge reversal | same | screen fail (+3.6 bp, 5m) |
| 7 | M6 extension mean reversion | same | screen fail |
| 7 | M7 session opening-range breakout | time of day | screen fail (systematically −8 bp) |
| 7 | M0 time-series momentum | returns | screen fail |
| 7 | M8 cross-asset lead-lag | **BTC → alt** | screen pass on 5m, **Stage 2 fail** (−0.229 R; CI fully < 0) |

**The plan-independent proof (Stage 1).** For every setup family, on every timeframe and 12
symbols, the mean signed forward move after the setup is within ±5 bp. The exception is the
+9.5 bp M8 pocket, which fails once executed. The hurdles are 14 bp for a taker round trip and
≈ 6 bp for an optimistic maker-assisted one. Typical 30-candle excursions are 45–165 bp. No stop
or target geometry can turn a ±5 bp drift into positive expectancy after these costs.

**What would change the picture** (not available to this app or to manual phone trading):
- information beyond OHLCV: order-book depth / imbalance, trade-by-trade aggressor flow,
  liquidation feeds, funding and open-interest dynamics (OKX serves only about 3 months of
  funding history);
- sub-second execution and maker-rebate fee tiers, which require API execution;
- longer horizons. 15m / 30m / 1h are already covered by Strategy 4.2, which is in forward test.

**Consequence.** No lower-timeframe BUY/SELL engine is activated, and no release is made.
v1.0.1 stays production. The scalp-6 analysis layer (EMA, S/R with strength, liquidity, BOS /
CHoCH, regime, direction) and the fast-7 market-state engine are kept in the codebase for future
use.
