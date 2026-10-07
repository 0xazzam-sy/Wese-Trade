# Wese Trade — Phase 5 Lower-Timeframe (1m / 5m / 10m) Strategy Research

> **Status: PRE-REGISTERED PROTOCOL.** This section was written and committed **before any
> development, validation or holdout result existed**. The gates below are fixed and must not
> be changed after results are read. Results are appended in later sections, with the commit
> of each run.
>
> Nothing here is a trading recommendation. Nothing places orders. A "no robust edge" outcome is
> a valid result. The production strategy for 15m/30m/1h
> (`wese-trade-forward-4.2-a03e20f1d4`, fingerprint `4.2-a03e20f`) is frozen and is not touched
> by this research.

## 0. Prior evidence (Phase 4.1, `docs/research.md`)

- 1m was **structurally dominated by friction**. Median 1m ATR was 0.063% against a 0.14%
  base round trip, and 98.5% of structural plans failed the cost floor.
- The 4.x engine on 5m was negative in validation (−0.125 R net, 1,135 trades).
- 10m was mildly positive (+0.047 R), but only on anchors and with a small sample.

The working hypothesis to beat is therefore **"no lower-timeframe edge survives costs"**.

## 1. Strategy family under research

- Name: `wese-trade-ltf-research-5.x`. Separately versioned, with its own fingerprint. It inherits
  **no** status from Strategy 4.2.
- One shared conceptual family for 1m / 5m / 10m. Each timeframe may get its own parameter
  profile, but only when the development evidence justifies it.
- Concept: **higher-timeframe-aligned pullback continuation with a closed-candle structural
  trigger**.
  1. **Context.** A higher-timeframe trend, from closed context candles only. Its direction is
     the EMA20/EMA50 stack, the EMA50 slope and the close's side of EMA50.
  2. **Pullback.** Execution-timeframe price retraces into value (touches EMA20) without a close
     beyond EMA50 by more than 1 ATR.
  3. **Trigger.** A closed candle that breaks the last confirmed micro swing (fractal, n = 2,
     confirmed only after 2 later candles), back in the context direction.
  4. **Stop.** The pullback's swing extreme plus a 0.1 ATR buffer. The minimum stop is 0.5 ATR,
     plus a cost floor (§3).
  5. **Targets.** TP1 = 1 R, TP2 = 2 R, TP3 = the nearest opposing confirmed swing beyond 2 R,
     else 3 R. One third exits at each target. A time stop applies after 48 execution candles.
  6. **Optional components (evaluated by ablation, kept only if they earn it):**
     - context filter;
     - displacement (trigger body ≥ 0.5 ATR);
     - candle confirmation (close in the outer third of the range);
     - liquidity sweep of the pullback low/high before the trigger;
     - relative volume ≥ 1.0;
     - volatility band (ATR percentile 10–90 over the trailing 500 candles);
     - extension guard (entry ≤ 2.5 ATR from EMA20);
     - session filter;
     - move to break-even after TP1.
- **Decisions use closed candles only**, so they cannot repaint. There is one position per
  symbol and timeframe at a time. The same trigger candle can never produce two signals.
  Re-entry requires a new trigger strictly after the previous trade's exit.

## 2. Data and splits (chronological; nothing is shuffled)

- **Universe.** The existing Phase 4.1 universe: 12 OKX USDT perpetuals selected by liquidity and
  listing age only, before any Phase 5 result:
  BTC, ETH, SOL, XRP, DOGE, HYPE, NEAR, UNI, PUMP, SUI, PEPE, ARB.
- **Raw data.** 5m for 730 days and 1m for 365 days (real OKX public candles). 10m, 15m, 30m and
  1h are aggregated from 5m, and only complete buckets are used.
- **Split boundaries (UTC), the same for every symbol and timeframe:**

| Segment | Range | Use |
| --- | --- | --- |
| Development | data start → 2026-03-31 | all design choices, grid, ablation, sensitivity |
| Validation | 2026-04-01 → 2026-06-30 | confirmation of the development pick only |
| **Untouched holdout** | **2026-07-01 → data end** | read **once**, after the candidate is frozen |

- **Walk-forward.** Four quarterly test folds: 2025-07–09, 2025-10–12, 2026-01–03 and 2026-04–06.
  For each fold, the parameter set is chosen on all data strictly before the fold (an expanding
  window), with the same selection rule as the final pick. The pooled out-of-sample result of
  these picks is reported.
- **Disclosed contamination.** Phase 4.1 inspected results of a *different* engine (the 4.x
  family) on 5m/1m data overlapping 2025-10 → 2026-10. No result of this Phase 5 family has
  been seen on any segment.

## 3. Costs (realistic friction; the decision uses net R)

| Scenario | Taker | Maker | Slippage per side (market) | Stop-exit extra slippage |
| --- | ---: | ---: | ---: | ---: |
| base | 0.05% | 0.02% | max(0.02%, 1 tick) | +0.02% (adverse execution) |
| high (stress) | 0.06% | 0.03% | max(0.05%, 1 tick) | +0.05% |

- **Market entries** pay taker + slippage.
- **Limit entries** pay maker and fill only if price trades **through** the limit by at least
  one tick. A touch is not a fill.
- **Take-profits** are maker limit orders. **Stops and time stops** are market orders.
- **Gaps through the stop** exit at the open. When a stop and a target share a candle, the stop
  is assumed first.
- **Cost floor.** A trade is skipped when the estimated round-trip cost exceeds a fraction `F` of
  its risk (`F` ∈ {0.10, 0.20}).
- **Tick size.** Prices are rounded to the instrument tick: entries/stops adversely, targets
  conservatively.
- **Minimum size.** OKX minimum contract value is far below a 1 R risk unit for every universe
  member, so it is reported but does not bind.
- **Reported for every result:** gross R, R after fees, and R after fees + slippage (= net).
  Decisions use **net, base** costs. The high scenario must also stay positive.

## 4. Baselines (same simulator, same costs, same splits)

- **B0 no-trade:** 0 R.
- **B1 simple trend continuation:** EMA20 > EMA50 and a close above the 20-candle high → long
  (mirrored for short). The stop is 1.5 ATR, the target 2 R, the time stop 48 candles.
- **B2 analysis directional bias:** entry when the trend direction and the main swing structure
  direction newly agree (the app's «ميل تحليلي»). The stop is 1.5 ATR, the target 2 R.

The candidate must beat B1 and B2 on development **and** on holdout (net, base).

## 5. Pre-registered search space (coarse; no unrestricted optimisation)

Per execution timeframe: 2 × 2 × 2 × 2 × 2 = **32 configurations**, plus single-component
ablations around the development pick.

| Dimension | Options |
| --- | --- |
| Context timeframe | 1m: {5m, 15m} · 5m: {15m, 1h} · 10m: {30m, 1h} |
| Displacement filter | off / on (body ≥ 0.5 ATR) |
| Cost floor F | 0.10 / 0.20 |
| Break-even after TP1 | off / on |
| Entry | market at the trigger close / limit at the trigger-candle midpoint (expires after 3 candles) |

- **Selection rule (development only).** Maximise net expectancy among configurations with
  ≥ 300 development trades. **Plateau rule:** every neighbour that differs in one dimension must
  have net E > 0 and ≥ 50% of the pick's E. Otherwise take the best configuration that satisfies
  it. If none satisfies it, the timeframe is rejected at development.
- **Ablation.** Each optional component is toggled alone from the pick, on development. A
  component stays only if removing it lowers net E **or** PF, without raising drawdown by more
  than 25%.

## 6. Production gates (fixed BEFORE validation and holdout are read)

All gates are evaluated **per timeframe**, at net R with base costs, unless stated otherwise.
A timeframe is *historically eligible* only if **every** gate passes.

| # | Gate | Threshold |
| --- | --- | --- |
| G1 | Development expectancy | net E ≥ +0.05 R, ≥ 300 trades |
| G2 | Validation expectancy | net E > 0, PF ≥ 1.10, ≥ 100 trades |
| G3 | Holdout expectancy | net E ≥ +0.05 R **and** the 90% CI lower bound (block bootstrap by day) > 0; ≥ 100 trades |
| G4 | Holdout profit factor | ≥ 1.15 |
| G5 | Walk-forward | pooled OOS net E > 0, and net E > 0 in ≥ 3 of 4 folds (≥ 30 trades per fold) |
| G6 | Drawdown (holdout) | max DD ≤ max(20 R, 0.25 R × trades) |
| G7 | Concentration (holdout) | E > 0 after removing the 2 best symbols, and ≥ 60% of symbols with ≥ 10 trades have E ≥ 0 |
| G8 | Cost stress (holdout) | net E > 0 under the high scenario |
| G9 | Sensitivity | the plateau rule holds (§5) |
| G10 | Baselines | net E > B1 and > B2 on development and holdout |
| G11 | Direction | long and short each net E > −0.05 R on holdout (no hidden one-sided loss) |
| G12 | Integrity | no-lookahead / no-repaint / split-overlap tests pass |

**Production activation additionally requires a forward test**, in a separate namespace
(`ltf-5.x`) that is never mixed with Strategy 4.2. It needs at least 28 days **and** 100 closed
forward trades per timeframe, net E > 0, and PF ≥ 1.05. Until then, 1m/5m/10m stay
«تحليل فقط» for normal users. Elapsed forward-test time cannot be produced by research and is
never simulated.

The strategy score is labelled «قوة توافق شروط الاستراتيجية». It is not a probability. Win rate
is reported but is **not** a gate.

---

## 7. Data quality (development + validation range; the holdout is not read)

5m, 730 days per symbol (HYPE 509 d and PUMP 450 d are limited by their listing dates). Real OKX
candles. **0 malformed rows, 0 duplicates (primary key).** Missing candles: 0–3 per symbol.

**Cleaning rule corrected before any result was read.** The first draft *dropped* "bad ticks"
(range > 25× the trailing median and > 8% of price). Inspection showed that every flagged candle
was a **real, continuous market event**: each opens at the previous close and is confirmed
across symbols. Examples:
- the 2025-10-10 liquidation cascade: ARB −61% and XRP −35% within one 5m candle;
- the 2024-12-05 BTC flash drop: −10% in 5 minutes.

Dropping them would delete the worst stop-outs and bias every result upward. They are now
**kept and only counted** (`extreme`). Gaps are never filled. Aggregated timeframes use complete
buckets only.

**Disclosed process slip.** During harness smoke testing, one aggregate (ETHUSDT, 5m, a single
default configuration, net −0.14 R) was computed over the full date range, which included the
holdout. No other holdout number exists. The loader now *refuses* holdout candles unless
explicitly unlocked (`HoldoutLockedError`, covered by a test).

## 8. LTF-5.0 development results (pre-registered grid, development segment only)

Net = after fees and slippage, base costs. 12 symbols. Development spans 541 days
(5m data start → 2026-03-31).

| TF | Configs | Best net E | Best gross E | Configs with net E > 0 | B1 net | B2 net | Selection |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 5m | 32 | −0.071 (n = 2,309, PF 0.86) | +0.004 | **0** | −0.307 | −0.297 | **rejected (G1)** |
| 10m | 32 | −0.077 (n = 4,988, PF 0.85) | +0.003 | **0** | −0.214 | −0.185 | **rejected (G1)** |

- LTF-5.0 loses less than both baselines, but every configuration is negative after costs.
- The **gross** expectancy is ≈ 0 everywhere, so the setup has **no directional edge even
  before friction**. Costs are 0.07–0.12 R per trade.

**Development diagnostics** (exploratory, independent trades, F = 0.20, n ≈ 15,000 per TF):
- No optional component (displacement, sweep, volume, candle confirmation, volatility band,
  extension) moves gross E by more than ±0.03 R.
- On 5m the alignment score is mildly **inverted**: score ≥ 90 gives −0.030 R gross, score 30
  gives +0.091 R gross.
- Longs and shorts are both ≈ 0 gross.
- 5m sessions: New York +0.027 R and London −0.056 R gross (likely noise at this size). 10m
  shows no session effect.
- The only regime consistent on both timeframes is **trending + high volatility**:
  - gross +0.030 R on 5m (n = 2,466);
  - gross +0.061 R on 10m (n = 1,898);
  - still negative net (−0.064 / −0.013 R).
- Per symbol, gross E ranges from −0.13 R (HYPE) to +0.05 R (PEPE). Nothing is robust.
- Exit decomposition: time exits average +0.64 R gross. Longer drift exists, but stop-outs at
  −1.13 R net dominate.

## 9. Pre-registration of ONE follow-up iteration: LTF-5.1 (written before it is run)

- **Hypothesis.** Taken from the single consistent development diagnostic: trend continuation
  works only when the higher timeframe is clearly trending **and** volatility is expanding, and
  it needs room to run.
- **Fixed changes from 5.0:**
  - regime gate: context strength ≥ 1.0 (|EMA20 − EMA50| / ATR on the context timeframe) **and**
    ATR percentile ≥ 80;
  - cost floor F = 0.10;
  - market entry.
- **Grid (8 configurations per TF):**
  - context TF (2 options);
  - time stop {48, 96} candles;
  - targets {standard 1/2/3 R thirds, runner: ½ at TP1 and ½ at TP3}.
- **Stricter development bar, because the same development data inspired the hypothesis:**
  - net E ≥ +0.05 R with ≥ 300 trades;
  - **and** net E > 0 separately for anchors (BTC/ETH/SOL) and for the other 9 symbols;
  - **and** gross E ≥ +0.10 R.
- If 5.1 fails development, **no further iteration is run in Phase 5**. The verdict is then
  "no robust lower-timeframe edge", and 1m/5m/10m stay «تحليل فقط».
- Validation and holdout are read only for a timeframe that passes this bar. The §6 gates apply
  unchanged.

## 10. LTF-5.1 development results (pre-registered in §9, development segment only)

| TF | Configs | Best net E | Best gross E | Development bar (net ≥ +0.05, gross ≥ +0.10, anchors > 0 and others > 0) |
| --- | ---: | ---: | ---: | --- |
| 5m | 8 | −0.026 (n = 917, PF 0.95) | +0.037 | **failed by all 8**: anchors and others disagree in sign; gross far below +0.10 |
| 10m | 8 | −0.023 (n = 855, PF 0.96) | +0.034 | **failed by all 8**: anchors −0.11 R in every configuration |

The trend + volatility-expansion gate halves the losses, but no configuration is positive after
costs. **Per §9, no further iteration is run for 5m/10m in Phase 5.** The validation and holdout
segments were **not read** for any configuration, and the holdout stays sealed.
