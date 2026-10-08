# Wese Trade — Phase 6: `wese-trade-scalp-6` fast-trading engine (1m / 5m / 10m)

> **Status: PRE-REGISTERED PROTOCOL.** This file was written and committed **before** the engine
> produced any result. The gates and search space below are fixed. Results are appended later,
> with the commit of each run. Nothing here is a trading recommendation, and nothing places
> orders.
>
> - Strategy 4.2 (`wese-trade-forward-4.2-a03e20f1d4` / `4.2-a03e20f`) stays the only engine for
>   15m/30m/1h and is not modified.
> - The rejected LTF-5.0/5.1 pullback family (`docs/research-ltf.md`) is **not** reused as a
>   foundation. Only its neutral infrastructure is reused: the data loader with the holdout
>   lock, the cost-aware simulator and the metrics.

## 1. Engine architecture: weighted confluence, few hard blockers

One incremental, closed-candle engine (`backend/app/scalp6/`). The same code serves the research
replay and the live app.

### 1.1 Analysis (always produced, signal or not)

- **EMA model:** a fast/mid/slow set, chosen per profile from §4. It reports:
  - ordering;
  - slope in ATR units;
  - price location and distance in ATR units;
  - compression / expansion of the fast–slow spread;
  - reclaim of the fast EMA.
- **Volatility:** Wilder ATR(14), its percentile over 300 candles, and a state: compressed (< 20) /
  normal / expanding (> 80) / extreme (≥ 99 or a candle range > 6 ATR).
- **Momentum:**
  - ROC over 6 candles in ATR units;
  - RSI(14), used *contextually*: level and slope relative to the trend, never fixed 70/30
    reversal rules;
  - consecutive directional closes;
  - candle displacement.
- **Volume:** relative volume (20 candles), plus expansion and contraction.
- **Market structure:**
  - fractal swings, confirmed only after `n` later candles;
  - HH / HL / LH / LL;
  - BOS (break in the structure's direction) and CHoCH (break against it);
  - major vs minor swings: major uses `n` = 2 × minor.
- **Support / resistance engine:**
  - levels are seeded only from confirmed swings;
  - levels within 0.3 ATR are merged into one zone;
  - **strength** = touches + rejection quality (wick / ATR) + flip bonus (a broken level retested
    from the other side) + volume at origin, all with a recency decay;
  - classes: weak / medium / strong;
  - only the strongest relevant levels are kept, at most 24 tracked and 3 displayed per side.
- **Liquidity:**
  - unswept swing highs are buy-side pools («سيولة علوية»); unswept swing lows are sell-side
    pools («سيولة سفلية»);
  - EQH / EQL are pools within 0.1 ATR;
  - a **sweep** is a wick through a pool with a close back inside;
  - a **failed breakout** is a close beyond a level followed by a close back inside within 3
    candles;
  - liquidity contributes evidence; **it never creates a signal alone**.
- **Regime:**
  - TRENDING: |EMA fast − EMA slow| ≥ 1 ATR, slope agreeing, and structure agreeing;
  - RANGING: spread < 0.5 ATR and volatility not expanding;
  - TRANSITIONAL otherwise.
- **Direction («الاتجاه العام»):** صاعد / هابط / عرضي, from a weighted blend of EMA order and
  slope, structure (BOS / CHoCH), momentum and higher-timeframe context. It is never an EMA
  crossover alone.
- **Higher-timeframe context:** EMA stack and slope of closed context candles. Disagreement
  *lowers* the score; it never kills a signal on its own.

### 1.2 Setup families (each has its own trigger and reasoning)

| Family | Trigger on the closed candle (long; short mirrored) | Natural entry | Structural stop |
| --- | --- | --- | --- |
| **A — trend continuation** | Pullback into the fast/mid EMA zone within the last 5 candles, then a close back above the fast EMA with a bullish candle | close, or limit at the fast EMA | below the pullback low − 0.2 ATR |
| **B — momentum breakout** | Compression (ATR percentile ≤ 30 within the last 20 candles), then a close above a medium/strong resistance with body ≥ 0.6 ATR | close, or limit retest of the broken level | below the broken level − 0.3 ATR, or below the breakout candle low |
| **C — liquidity sweep / reversal** | Sweep of a support or sell-side pool within the last 3 candles, then a close back above it (reclaim) with a bullish close | close, or limit at the reclaimed level | below the sweep extreme − 0.2 ATR |
| **D — regime-adaptive** | A + B in TRENDING · C (+ B out of the range) in RANGING · all families −10 score in TRANSITIONAL | per family | per family |

### 1.3 Score: «قوة الإشارة» 0–100 (confluence, **not** a probability of winning)

- Components in [−1, +1], from the long side's view (the short side is the mirror): trend, EMA
  location, structure, support/resistance location, liquidity, momentum, volume, candle,
  higher-timeframe context.
- Weights are **fixed a priori per family**: A favours trend/structure/HTF, B
  momentum/volume/candle, C S/R/liquidity/candle. They are not fitted.
- `score = 50 + 50 × weighted mean`.
- **BUY** when a long family triggered, `score_long ≥ T` and `score_long − score_short ≥ 10`.
  SELL is the mirror. Otherwise **NEUTRAL**, with the real reasons.
- A component may be neutral or even opposite; no single component is required.

### 1.4 Plan

- **Targets from structure:**
  - TP1 = the nearest opposing level or liquidity pool ≥ 0.8 R away, else 1 R;
  - TP2 = the next level ≥ TP1 + 0.5 R, else 2 R;
  - TP3 = the next level, measured move or ATR projection ≥ TP2 + 0.5 R, else 3 R.
- **R:R** is reported for TP1, TP2 and TP3.

### 1.5 Hard blockers (safety and data quality only)

- stale or incomplete data (warm-up after any gap);
- extreme volatility;
- impossible stop (risk > 4 ATR);
- TP2 < 1.0 R (structurally poor);
- friction > 25% of risk (taker round trip incl. slippage; fixed, not tuned).

## 2. Data and splits

The same data and **the same sealed holdout** as Phase 5. The holdout was never read for any
strategy:
- 12 OKX perpetuals (BTC, ETH, SOL, XRP, DOGE, HYPE, NEAR, UNI, PUMP, SUI, PEPE, ARB);
- 1m for 365 days; 5m for 730 days, with 10m/15m/30m/1h aggregated from 5m.

| Segment | Range (UTC) | Use |
| --- | --- | --- |
| Development | data start → 2026-03-31 | all choices |
| Validation | 2026-04-01 → 2026-06-30 | confirms the development pick |
| **Sealed holdout** | **2026-07-01 → 2026-10-07** | read **once**, after the candidate is frozen |

Walk-forward uses the 4 quarterly folds of Phase 5 (expanding training window).

## 3. Costs (unchanged from Phase 5, base scenario for decisions)

- Taker 0.05%, maker 0.02%, slippage max(0.02%, 1 tick) per market side, plus 0.02% extra on stop
  exits.
- Stress scenario: 0.06% / 0.03% / 0.05% / 0.05%.
- Manual phone execution is assumed to be **taker** unless an entry is a resting limit order.
- Limit orders fill only **through** the price and expire after 3 candles. A limit entry not
  filled before price reaches TP1 or the stop is «فاتت منطقة الدخول» (missed) and counts as no
  trade.
- TP partials: one third at each of TP1, TP2 and TP3. Stop-first when a stop and a target share
  a candle. Gaps through the stop exit at the open.

## 4. Pre-registered search space (per timeframe: 2 × 2 × 4 × 2 × 2 = 64 configurations)

| Dimension | Options |
| --- | --- |
| EMA set | (9, 21, 50) · (20, 50, 200) |
| Context TFs | 1m: {5m+10m, 5m+15m} · 5m: {10m+15m, 15m+1h} · 10m: {15m+30m, 30m+1h} |
| Families | A only · B only · C only · D adaptive |
| Score threshold T | 60 · 70 |
| Entry | market at the signal close · limit (A: fast EMA, B: broken level, C: reclaimed level) |

- Fixed, not searched: fractal `n` (1m: 3, 5m/10m: 2), ATR 14, RSI 14, margin 10 and the blocker
  values.
- **Selection (development only):** best net E with ≥ 300 development trades whose one-step
  neighbours (EMA set, context, T, entry) all have net E > 0 and ≥ 50% of its E. Simpler wins a
  tie within 0.01 R: fewer families, then market entry.
- **Architectures A, B, C and D are each reported separately.** The final system may use the
  strongest validated family or families per timeframe.

## 5. Gates (fixed before any result; per timeframe; net R at base costs)

| # | Gate | Threshold |
| --- | --- | --- |
| G1 | Development | net E ≥ +0.03 R, ≥ 300 trades, PF ≥ 1.05 |
| G2 | Validation | net E > 0, PF ≥ 1.05, ≥ 100 trades |
| G3 | Holdout | net E > 0 **and** 90% day-block bootstrap CI lower bound > −0.02 R; ≥ 100 trades |
| G4 | Holdout PF | ≥ 1.10 |
| G5 | Walk-forward | pooled OOS net E > 0, positive in ≥ 3 of the available folds |
| G6 | Holdout drawdown | ≤ max(20 R, 0.25 R × trades) |
| G7 | Concentration (holdout) | E > 0 without the best 2 symbols; ≥ 50% of symbols (≥ 10 trades) have E ≥ 0 |
| G8 | Cost stress (holdout) | net E > −0.02 R under the high scenario |
| G9 | Sensitivity | plateau rule of §4 |
| G10 | Baselines | net E > B1 and > B2 (Phase 5 baselines) on development and holdout |
| G11 | Direction | BUY and SELL each net E > −0.05 R on holdout |
| G12 | Integrity | no-lookahead / no-repaint / split tests pass |

- **Win rate is reported, never a gate.** A high win rate with negative expectancy fails.
- **Production activation** on a timeframe requires all of G1–G12. After activation the
  live signals are tracked in their own forward namespace (`scalp-6`), separate from Strategy 4.2.
- A timeframe that fails stays «تحليل فقط» **for signals**. Its analysis (EMA, S/R, liquidity,
  structure, regime, direction) still ships.

---

## 6. Pre-result engineering fixes (made before any trade outcome was read)

These were found from **trigger counts and level statistics only**. No P&L had been computed when
they were fixed (commit `ec8345a`):
- **Level touches counted chop.** Price oscillating around a level counted a touch on every
  candle, so every level graded "strong". A touch now counts only on a genuine revisit (≥ 1 ATR
  away since the last one).
- **Break / flip lifecycle.** A break is a decisive close beyond the level by more than 0.5 ATR.
  The first break flips the level's role. A level broken back again is chop and is removed.
- **Swing seeding bug.** New swings were detected by list length, and the list is capped at 40,
  so levels stopped being seeded after 40 swings. The tracker now returns the swings each candle
  confirms.
- **Breakout one-shot guard.** It used Python object ids, which are reused after garbage
  collection, so new levels were treated as "already used" and family B fired 21 times in
  180 k candles. It is now a flag on the level.
- **Grade cut-offs.** Taken from the level-strength distribution, not from outcomes: strong
  ≥ p80 (7.9), medium ≥ p45 (3.8), measured over 25 k level samples on BTC 1m, ETH 5m and DOGE 5m
  development data.

## 7. Development results (pre-registered grid, development segment only)

Net = after fees and slippage, base costs. 12 symbols. 64 configurations per timeframe.
"/day" = signals per day across the whole universe. "L / S" = BUY / SELL net expectancy.

| TF | Days | Configs net E > 0 | Architecture | Best config | Trades | Win | Gross | After fees | **Net** | PF | Max DD | /day | L / S |
| --- | ---: | ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1m | 176 | **0 / 64** | A | ctx 5m+10m, EMA 9/21/50, T 70, market | 14,593 | 40.6% | −0.001 | −0.112 | **−0.180** | 0.69 | 2,655 R | 83 | −0.21 / −0.16 |
| | | | B | ctx 5m+10m, EMA 20/50/200, T 60, market | 633 | 36.8% | −0.022 | −0.140 | **−0.220** | 0.66 | 145 R | 3.6 | −0.17 / −0.28 |
| | | | C | ctx 5m+10m, EMA 20/50/200, T 60, market | 3,049 | 36.5% | −0.032 | −0.148 | **−0.225** | 0.67 | 688 R | 17 | −0.21 / −0.24 |
| | | | D | ctx 5m+10m, EMA 9/21/50, T 70, market | 11,955 | 40.3% | −0.000 | −0.111 | **−0.180** | 0.69 | 2,179 R | 68 | −0.22 / −0.14 |
| 5m | 541 | **0 / 64** | A | ctx 15m+1h, EMA 20/50/200, T 60, market | 28,175 | 39.9% | +0.025 | −0.068 | **−0.120** | 0.80 | 3,384 R | 52 | −0.13 / −0.11 |
| | | | B | ctx 15m+1h, EMA 20/50/200, T 60, market | 5,499 | 34.8% | +0.013 | −0.092 | **−0.153** | 0.78 | 843 R | 10 | −0.19 / −0.11 |
| | | | C | ctx 15m+1h, EMA 20/50/200, T 70, market | 9,118 | 35.5% | −0.003 | −0.104 | **−0.163** | 0.76 | 1,482 R | 17 | −0.18 / −0.15 |
| | | | D | ctx 15m+1h, EMA 9/21/50, T 70, limit | 21,880 | 37.1% | −0.009 | −0.088 | **−0.125** | 0.80 | 2,738 R | 40 | −0.14 / −0.11 |
| 10m | 541 | **0 / 64** | A | ctx 30m+1h, EMA 9/21/50, T 70, market | 19,656 | 41.6% | +0.025 | −0.046 | **−0.085** | 0.85 | 1,678 R | 36 | −0.11 / −0.06 |
| | | | B | ctx 15m+30m, EMA 9/21/50, T 70, market | 5,276 | 33.6% | −0.005 | −0.102 | **−0.158** | 0.77 | 840 R | 10 | −0.20 / −0.12 |
| | | | C | ctx 30m+1h, EMA 9/21/50, T 60, market | 17,151 | 34.3% | +0.009 | −0.087 | **−0.141** | 0.79 | 2,427 R | 32 | −0.16 / −0.12 |
| | | | D | ctx 15m+30m, EMA 9/21/50, T 70, market | 17,987 | 40.6% | +0.027 | −0.048 | **−0.089** | 0.84 | 1,609 R | 33 | −0.12 / −0.06 |

D with a limit entry (5m) missed 22,541 entries (no fill before TP1 or the stop). They are counted
as no trade.

## 8. Verdict

**No scalp-6 architecture passes G1 on any timeframe.** That covers trend continuation (A),
momentum breakout (B), liquidity sweep / reversal (C) and the regime-adaptive combination (D),
in all 192 pre-registered configurations. Validation was never evaluated, and the holdout is
**still sealed**.

**Why.** Across all four architectures, the gross expectancy of 1m–10m setups built from
OHLCV-based analysis (EMA, S/R, liquidity, structure, momentum, volume, regime) is ≈ 0 (between
−0.03 and +0.03 R). Realistic manual-execution friction costs 0.07–0.18 R per trade, so every
configuration ends at −0.08 R or worse:
- the costs are taker fees + spread/slippage on entries, stops and time exits;
- the friction blocker already rejects most structurally tight setups.

This repeats, with a completely different signal model, the Phase 5 finding (LTF-5.0/5.1).
Together the two phases cover 5 distinct strategy designs and 312 configurations on 12 symbols.
Win rates of 34–42% with these losses show that a "high-accuracy" presentation would be
misleading.

**Consequence.**
- BUY/SELL on 1m / 5m / 10m are **not activated**.
- The scalp-6 **analysis** (EMA, support/resistance with strength, liquidity, structure, regime,
  direction) is sound and does not depend on signal profitability. Per §5 it can ship for these
  timeframes.
- Strategy 4.2 (15m/30m/1h) is unchanged.
