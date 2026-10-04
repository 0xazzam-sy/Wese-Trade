# Wese Trade — Phase 4.1 Signal Edge Research

> **Purpose.** Determine, scientifically, whether a robust positive-expectancy configuration
> of the signal engine exists. Not to make the numbers look good. A "no robust edge"
> conclusion is a valid outcome. Nothing here is a trading recommendation, and nothing
> places orders.

## Verdict (read this first)

**No robust edge was found.** The frozen Phase 4 baseline stays **غير مُثبت (unproven)** and
is labelled «تجريبي» in the UI. No configuration earned forward-test status.

| | Validation trades (W1–W3) | Net E[R] | PF | W1 / W2 / W3 | Never-inspected symbols |
| --- | ---: | ---: | ---: | --- | --- |
| Baseline `f26f636443`, 12 symbols | 2,605 | **−0.077** | 0.87 | −0.098 / −0.028 / −0.105 | −0.096 (n=1,794) |
| Best pre-registered candidate grid (64 variants) | — | — | — | **0 of 64 pass, in any scope** | — |

- The Phase 4 hint (TREND_CONTINUATION) partly survives: +0.024 R in validation, but −0.083 R
  in the pre-period, and negative on fresh symbols (−0.019 R).
- An **exploratory, post-hoc** trend refinement (retrace entry + runner exit) shows +0.32 R in
  W1–W3. However:
  - it was designed after seeing those windows;
  - it was **negative in the pre-period**;
  - several symbols are negative;
  - 15m was flat in W3.

  It is recorded as a research candidate (`wese-trade-research-4.1-c590e82e3a`, status
  `testing`). It is **not** promoted, and it needs a prospective test on data after
  2026-10-04.


---

## 1. Frozen baseline

- The Phase 4 strategy **`wese-trade-signal-4.0-f26f636443`** is frozen.
  `DEFAULT_SIGNAL_CONFIG` is unchanged, and a test (`tests/signals/test_validation.py`)
  fails if its version ever changes.
- Every research configuration gets its own version,
  `wese-trade-research-4.1-<sha256(variant definition + baseline)[:10]>`. The name and
  notes of a variant are not part of the hash.
- **Reproduction.** A fresh pass-1 replay of the baseline on the Phase 4 data reproduced
  the Phase 4 report **bit-exactly** (development 719 trades, −0.019 R; holdout 298
  trades, −0.126 R, PF 0.80; identical per-setup and calibration tables).
- **Research pipeline parity.** On real series (BTC 1h, ETH 15m, SOL 5m), the research
  pipeline (pass 1 + the `baseline` variant in pass 2) produces **identical** signals to
  the canonical replay. A unit test enforces this on the fixture.

The only engine-side change is an optional `target_filter` hook in `build_plan` (used only
by the research "liquidity-first" target model). Its default leaves every plan
unchanged, which the bit-exact reproduction confirms.

## 2. Data

**Research store.** `backend/data/research/candles.sqlite` (git-ignored). It is
separate from the app database and from live signal persistence.
- One row per (symbol, timeframe, open time): OHLCV as exact decimal strings, the
  `closed` flag (only closed candles are stored) and the `source`.
- Inserts never overwrite a stored row. A re-download that disagrees with stored values
  is counted as a conflict and reported.
- Funding history has its own table, as do research run summaries (`research_runs`).

**Download.** `python -m app.scripts.research_fetch`:
- public OKX `history-candles`, 100 per request;
- a polite 5 req/s token bucket, at most 2 series in flight;
- patient retries on rate limits;
- every page is inserted as it arrives, so a restart resumes where it stopped.

**Universe.** `python -m app.scripts.research_fetch --select`. Symbols are chosen by
**liquidity and history only, never by strategy results**:
1. live linear USDT perpetuals with `instCategory = 1` (crypto; excludes e.g. XAU);
2. listed at least 400 days ago;
3. pre-ranked by 24h quote volume (top 40), then ranked by the **mean daily quote volume
   of the last 30 closed days**;
4. BTC, ETH and SOL are always included as anchors, plus the next 9.

Known biases: survivorship (only currently listed instruments are eligible), and the
ranking uses current liquidity.

**Data obtained** (all real OKX public candles, 0 conflicts, 1 gap: SOL 1m):

| Timeframe | BTC / ETH / SOL (anchors) | 9 added symbols |
| --- | --- | --- |
| 1h | 1,095 days | 730 days (HYPE 590, PUMP 447: listing limits) |
| 30m | 730 days | 365 days |
| 15m | 365 days | 365 days |
| 5m | 365 days | 365 days |
| 10m | 365 days (aggregated from 5m) | — (not studied) |
| 1m | 180 days (259k candles each) | — (research-only, see §4) |

Funding history: OKX serves only about 3 months (from 2026-06-29), 292 settlements per symbol.

**Symbols** (selected 2026-10-04, 30-day mean daily quote volume):
- Anchors: BTC 5.83B, ETH 6.73B, SOL 1.10B.
- Added: XRP 526M, DOGE 373M, HYPE 254M, NEAR 197M, UNI 192M, PUMP 163M, SUI 158M,
  PEPE 152M, ARB 133M.

Strategy performance played no part in the choice.


## 3. Methodology

### 3.1 Two passes, canonical engines

- **Pass 1** (`research/collect.py`) replays every series sequentially with the canonical
  `MarketAnalyzer`, using exactly the backtester's context rule (a context candle is
  consumed only once it has closed by the execution close). At every candle that
  confirmed a structure event, it records:
  - the canonical baseline evaluation;
  - **every** hypothesis of **every** family and side, scored by the canonical
    `SignalEngine._score`;
  - plans built by the canonical `build_plan` under a fixed set of plan models (§3.4);
  - compact side-adjusted features.
- **Pass 2** (`research/simulate.py`) re-selects hypotheses for a research `Variant`,
  mirroring `SignalEngine.classify` exactly, and runs the canonical `SignalTracker`
  (dedupe, cooldown, fills, stop-first ambiguity, gaps, expiry, time stop, costs).

### 3.2 Walk-forward validation (new; the old holdout is contaminated)

The Phase 4 70/30 holdout was inspected, so it is **not** used as a fresh holdout and
nothing is tuned on it. Instead, there are three **calendar** validation windows, shared
by every symbol and timeframe:

```
pre-period (all history before W1) | W1 (91 d) | W2 (91 d) | W3 (91 d, ends at the data end)
```

- **Development for window Wk** = everything strictly before Wk starts (an expanding
  window). Validation never overlaps development; this is tested.
- **Design decisions** (score weights, kept penalties) use the **pre-period only**.
  W1–W3 are reported separately and never feed design.
- **Candidate selection** is itself walk-forward. For each Wk, the candidate with the
  best *development* expectancy (≥ 100 development trades) is chosen, and its Wk result
  is recorded. The aggregate of those three picks is an honest out-of-sample estimate
  of the selection procedure.
- **Contamination.** For BTC/ETH/SOL, W2–W3 overlap the inspected Phase 4 holdout. The 9
  added symbols were never inspected. Results are reported as *fresh* vs *anchor*, and
  the verdict requires the fresh symbols to be positive too.

### 3.3 Sample-size rules

| Rule | Value |
| --- | --- |
| Group reported without a warning | ≥ 50 validation trades (else `INSUFFICIENT_SAMPLE`, ⚠) |
| Candidate eligible to pass | ≥ 30 validation trades in **each** window and ≥ 150 in total |

### 3.4 Variants studied (limited, category-level; no brute force)

| Dimension | Options |
| --- | --- |
| Families | each family alone; trend; trend + pullback; all but reversal; all |
| Timeframes | 5m, 15m, 30m, 1h (signal research); 1m, 10m research-only (anchors) |
| Regime filter | none / exclude `range` + `transitional` |
| Entry | **A** confirmation close (market) · **B** retrace: limit at the confirmation candle's midpoint (never worse than the close, never inside the cost floor) · **C** supporting OB/FVG edge (only setups that have one, compared on the same subset) · **D** 5m execution (§3.6) |
| Stop | **A** structure anchors (engine) · **B** aligned liquidity-sweep extreme first · **C** supporting order-block edge first (B and C fall back to A's anchors) |
| Target | **A** structural (engine) · **B** liquidity-first (pools + swing levels only) · **C** runner (½ at TP1, ½ at TP3, hold up to 96 bars) |
| TP1 behaviour | break-even after TP1 off (default) / on (research variant) |
| Score | baseline engine score / `s41` (re-weighted from pre-period evidence, §3.5) |
| Threshold | 65, 70, 75, 80 (broad regions; single magic values are rejected) |
| Costs | low / base / high (§3.7) |

### 3.5 Score research

Each hypothesis with a valid plan is traded **in isolation** (no cooldown/overlap rules)
to get one outcome per hypothesis. For every score component:
- Spearman correlation with net R in the pre-period;
- expectancy by quintile;
- stability by window, timeframe, and anchor vs fresh symbols.

The `s41` model keeps only components whose pre-period correlation is positive beyond
2 standard errors **and** positive for both anchors and fresh symbols, weighted by that
correlation. It keeps only the penalties under which penalized hypotheses did worse in
the pre-period. If nothing qualifies, the model is a null model and is reported as such.

### 3.6 Lower-timeframe execution (15m/30m setups, 5m timing)

The thesis stays the HTF signal: stop and targets are unchanged. Only the entry moment
moves, using information available at that moment. All variants are managed on the
**same 5m path** with the tracker's rules:
- **A5:** enter at the HTF confirmation close.
- **D5:** first aligned 5m internal CHoCH confirmed strictly after the HTF confirmation.
- **D5b:** wait for a 5m candle that trades back to the HTF confirmation-candle midpoint,
  then take the first aligned 5m internal BOS/CHoCH.

Cancellation and scope:
- D5/D5b are cancelled if a 5m candle closes beyond the stop or trades through TP1
  before the fill, or if nothing happens within the HTF expiry window.
- Only market-entry HTF signals are used, since zone signals already use a limit.
- Comparisons include total R per HTF signal, because a filter that skips trades must
  still win in total.

A test enforces that a 5m entry can never precede the HTF confirmation.

### 3.7 Costs

| Scenario | Taker | Maker | Slippage | Meaning |
| --- | ---: | ---: | ---: | --- |
| low | 0.04% | 0.01% | 0.01% | favourable but plausible (VIP tier, tight books) |
| **base** | **0.05%** | **0.02%** | **0.02%** | Phase 4 assumptions, unchanged |
| high | 0.06% | 0.03% | 0.05% | stress (thin books, fast markets) |

- Plans (and the 5× cost-floor) are always built with base costs, so the three scenarios
  evaluate the **same trades**.
- Only net R changes; gross R is identical across scenarios.

### 3.8 Acceptance criteria (research, not a guarantee)

A candidate **passes** only if **all** of these hold:
- the sample rules (§3.3) are met;
- expectancy > 0 and profit factor > 1.0 in **each** of W1, W2 and W3;
- validation profit factor ≥ 1.1;
- validation expectancy stays positive after removing the best symbol;
- validation expectancy on fresh symbols is positive;
- validation max drawdown ≤ max(15 R, 0.2 R × trades).

Score tiers must not be grossly inverted, and an edge that exists only at a single
threshold is treated as overfit. Ranking within passing candidates is by validation
expectancy, then PF, drawdown, cross-window stability and symbol stability. Win rate is
not a ranking criterion.

---

## 4. Timeframe cost efficiency

Round-trip cost at base: 0.14% of price (taker + slippage on both sides).

| TF | Median ATR % | Cost R if the stop were 1 ATR | Structural plans rejected by the 5× cost floor | Median plan risk % | Median realized cost R | Verdict |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1m | 0.063 | 2.24 | **98.5%** | 0.70 | 0.176 | **STRUCTURALLY UNSUITABLE** |
| 5m | 0.287 | 0.49 | 35.2% | 0.82 | 0.129 | OK on cost, but negative results (§5) |
| 10m | 0.287 | 0.49 | 35.0% | 0.78 | 0.129 | OK on cost (anchors only) |
| 15m | 0.533 | 0.26 | 6.7% | 1.18 | 0.093 | OK |
| 30m | 0.740 | 0.19 | 2.3% | 1.51 | 0.073 | OK |
| 1h | 1.205 | 0.12 | 0.1% | 2.40 | 0.046 | OK |

**1m is mathematically dominated by friction.**
- A structural 1m stop is a fraction of the round-trip cost. 98.5% of 1m plans cannot even
  exist under the cost floor.
- The 31 that did trade lost −0.310 R.
- 1m stays **research-only and visual context**. It is not used even as micro-execution in
  this phase; 5m is the execution study (§10).

## 5. Baseline on the new methodology

Baseline `f26f636443`, all timeframes:

| Period | Trades | Win | Gross E[R] | Net E[R] | PF | Max DD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| pre-period | 1,380 | 35.5% | −0.045 | −0.137 | 0.78 | 192.2 R |
| W1 | 806 | 36.1% | +0.016 | −0.098 | 0.84 | 104.7 R |
| W2 | 876 | 40.2% | +0.082 | −0.028 | 0.95 | 47.8 R |
| W3 | 923 | 36.2% | −0.001 | −0.105 | 0.83 | 126.5 R |
| **validation** | **2,605** | 37.5% | +0.032 | **−0.077** | 0.87 | 227.6 R |

Validation breakdowns (net E[R] / trades):

| Dimension | Values |
| --- | --- |
| Timeframe | 5m −0.125 (1,135) · 10m +0.047 (193) · 15m −0.038 (698) · 30m −0.099 (408) · 1h +0.061 (140) · 1m −0.310 (31 ⚠) |
| Symbol | BTC +0.032 · ETH +0.043 · SOL −0.124 · XRP −0.148 · DOGE −0.026 · HYPE −0.123 · NEAR −0.214 · UNI −0.036 · PUMP −0.181 · SUI +0.008 (20 ⚠) · PEPE +0.061 · ARB +0.015 |
| Family | trend −0.002 (546) · pullback −0.013 (699) · breakout −0.138 (1,293) · reversal −0.184 (67) |
| Regime | uptrend −0.045 · downtrend −0.061 · strong_up −0.053 · strong_down −0.199 · range −0.116 · transitional −0.164 |
| Side | long −0.052 (1,329) · short −0.104 (1,276) |

Score calibration (validation) is **still inverted at the top**: 75–79 −0.077 (1,705),
80–84 −0.035 (703), 85–89 −0.248 (174), 90+ −0.069 (23 ⚠).

## 6. Cost scenarios (same trades; only net R changes)

| Variant | Low | Base | High |
| --- | ---: | ---: | ---: |
| Baseline, validation E[R] | −0.044 | −0.077 | −0.139 |
| Trend only, validation E[R] | +0.059 (PASS*) | +0.024 | −0.044 |

\* Trend-only "passes" **only under favourable costs**. Results are never promoted on the
low-cost scenario.

## 7. Setup families in isolation (threshold 75, signal timeframes)

| Family | Pre-period | W1 | W2 | W3 | Validation (n) | Gross | Fresh | Status |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| TREND_CONTINUATION | −0.083 | +0.031 | +0.054 | −0.011 | **+0.024** (631) | +0.142 | −0.019 | FAIL |
| PULLBACK_CONTINUATION | −0.070 | −0.037 | −0.041 | +0.004 | −0.023 (691) | +0.056 | −0.006 | FAIL |
| BREAKOUT_CONTINUATION | −0.200 | −0.263 | −0.038 | −0.200 | −0.159 (1,266) | −0.043 | −0.177 | FAIL |
| LIQUIDITY_REVERSAL | −0.170 | −0.058 | −0.110 | −0.151 | −0.110 (392) | +0.003 | −0.049 | FAIL |

At threshold 65 every family is worse:
- trend −0.117 (3,079)
- pullback −0.070
- breakout −0.161
- reversal −0.132

**Trend by timeframe:**
- 5m −0.046 (289)
- 15m +0.008 (189)
- 30m +0.121 (121)
- 1h +0.375 (32 ⚠)

**Trend by symbol:**
- positive: BTC +0.306, ETH +0.135, ARB +0.153, DOGE +0.142, PEPE +0.076, PUMP +0.094,
  SOL +0.057
- negative: HYPE −0.213, NEAR −0.146, UNI −0.054, XRP −0.060, SUI −0.418 (10 ⚠)

**Trend by side:** long +0.041 (293), short +0.009 (338).

**Trend by regime:** uptrend +0.077, downtrend +0.020, strong_down −0.015, strong_up −0.095.

**Breakout** is negative before costs in the pre-period and in validation, on every
timeframe and both sides. The structure-break + displacement + volume trigger does not
predict continuation on this data.

### Reversal diagnosis (isolated outcomes, n = 4,415)

| Hypothesis | Evidence |
| --- | --- |
| HTF conflict | No. It is negative whether the HTF is opposed (−0.168), neutral (−0.159) or aligned (−0.235). |
| Weak sweeps | No. Strong sweeps (liquidity ≥ 0.75) give −0.165; weak ones −0.184. |
| Structure reaction too early | Internal CHoCH −0.148, internal BOS −0.203: both negative. |
| Stop placement | 1–2 ATR stops −0.279, ≥ 2 ATR −0.132 (wider is less bad, still negative). |
| Regime mismatch | Negative in every regime with sample (range −0.107, downtrend −0.241, transitional −0.146). |
| Costs | Gross E[R] −0.054. **No edge even before costs.** |
| Sample | Sufficient (4,415 isolated, 392 tracked validation trades). |

No clear, robust explanation emerges. LIQUIDITY_REVERSAL is marked **EXPERIMENTAL /
DISABLED_FOR_SIGNALS** (deployment policy; the implementation is kept). BREAKOUT_CONTINUATION
gets the same status on the same grounds.

### Range / transitional regimes

TREND_CONTINUATION already rejects `range` by rule. Excluding `transitional` as well changed
almost nothing (627 vs 631 validation trades, +0.027 vs +0.024 R). Those regimes are
already effectively ineligible for trend, so no rule change is needed. For all families,
excluding both made no difference (−0.076 vs −0.077 R).

## 8. Entry, stop and target models

**Entry (validation E[R]; trades):**

| Model | Trend | All families |
| --- | ---: | ---: |
| A close (market) | +0.024 (631) | −0.090 (2,384) |
| B retrace (confirmation-candle midpoint) | **+0.106** (555) | −0.032 (2,103) |
| C zone vs A, same subset (setups with a zone) | +0.030 vs +0.013 | −0.033 vs −0.082 |

Retrace improves on market entry for **every** family set and in the pre-period too
(trend −0.040 vs −0.083). It is the most consistent improvement found, and it fills about
12% fewer trades.

**Stops** (trend, validation E[R] / median risk / median cost R):

| Model | E[R] | Median risk | Median cost |
| --- | ---: | ---: | ---: |
| A structure | +0.024 | 2.16 ATR | 0.127 R |
| B sweep extreme | +0.019 | 2.17 ATR | 0.127 R |
| C order-block edge | +0.044 | 2.23 ATR | 0.123 R |

All families: A −0.084, B −0.088, C −0.085.

The models differ by little because the risk floor and the 3 ATR ceiling dominate. No stop
model changes the picture, so **A is kept**.

**Targets / TP1 behaviour** (trend validation E[R]; all families in brackets):

| Model | Trend | All families |
| --- | ---: | ---: |
| A structural | +0.024 | −0.090 |
| B liquidity-first | +0.037 | −0.084 |
| C runner (½ TP1, ½ TP3, 96-bar hold) | **+0.062** (PASS in isolation) | −0.057 |
| Break-even after TP1 | −0.032 | −0.088 |

Break-even after TP1 makes results worse again, so it **stays disabled**.

## 9. Score research

**Components.** Spearman correlation with net R over 12,614 isolated pre-period hypotheses
(2 standard errors ≈ 0.018):

| Component | ρ pre | W1 | W2 | W3 | Pre anchors | Pre fresh |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| htf | −0.001 | −0.017 | +0.066 | +0.066 | +0.003 | −0.000 |
| structure | +0.008 | −0.000 | +0.043 | +0.029 | +0.017 | +0.005 |
| liquidity | −0.011 | +0.019 | −0.014 | −0.023 | −0.021 | −0.008 |
| location | +0.013 | −0.023 | +0.025 | +0.039 | −0.016 | +0.029 |
| trend | −0.018 | −0.036 | −0.005 | −0.008 | −0.011 | −0.017 |
| displacement | +0.009 | −0.003 | +0.022 | +0.027 | +0.034 | −0.000 |
| volume | +0.004 | −0.004 | +0.021 | +0.016 | +0.008 | +0.008 |
| candle | +0.001 | −0.006 | −0.002 | +0.004 | +0.031 | −0.013 |
| momentum | −0.024 | −0.003 | +0.017 | −0.016 | −0.049 | −0.013 |

The baseline score itself has ρ = +0.001.

- **No component carries stable predictive information.** None clears 2 standard errors
  with a consistent sign across anchors and fresh symbols.
- The derived `s41` model is therefore a **null model** (structure only), and it performs
  no better (−0.108 R, every threshold).
- The redesign conclusion is **not** "new weights". It is: **the current confluence
  components do not rank setup quality.** They remain visible as analysis context.
- Removing them from scoring would leave no score at all, so the score stays a
  transparency display and is never a quality claim.

**Penalties (pre-period, E[R] with vs without):**

| Penalty | With | Without | Verdict |
| --- | ---: | ---: | --- |
| htf_first_opposed | −0.201 | −0.097 | useful |
| opposite_divergence | −0.154 | −0.093 | useful |
| adverse_sweep | −0.130 | −0.092 | useful |
| extreme_location | −0.133 | −0.087 | useful |
| overextended | **+0.060** | −0.106 | **wrong direction** |
| transitional_regime | −0.063 | −0.107 | **wrong direction** |
| volume_contradiction | −0.099 | −0.100 | no effect |
| extreme_volatility | −0.100 | −0.100 | no effect |

**Double counting** (Pearson, pre-period):

| Pair | r |
| --- | ---: |
| `trend` vs `regime_aligned` | 0.87 |
| `trend` vs HTF-1 trend | 0.90 |
| `htf` vs HTF-1 trend | 0.73 |
| `htf` vs `trend` | 0.63 |
| `structure` vs `swing_aligned` | 1.00 (same fact) |

EMA trend, regime and HTF context largely encode the **same** information. Today they
contribute 30 points (htf 20 + trend 10), plus regime penalties, for what is essentially one
fact. Since none of them is predictive, reweighting cannot help. Any future score must
merge them into one "trend context" category.

**Interactions** (pre-period E[R]): none produced a cell that was positive and also
positive in validation.
- HTF aligned & swing aligned: −0.177 (n=4,963) vs not-HTF & swing: −0.039.
  HTF alignment did **not** help.
- Sweep & internal CHoCH: −0.093.
- Order block & discount: −0.080.
- Displacement & relative volume on a swing BOS: −0.100.

**Calibration buckets** (validation, baseline score at threshold 60, 9,752 trades):

| Bucket | E[R] (trades) |
| --- | --- |
| 60–64 | −0.135 (2,897) |
| 65–69 | −0.101 (2,746) |
| 70–74 | −0.148 (2,068) |
| 75–79 | −0.064 (1,323) |
| 80–84 | −0.062 (562) |
| 85–89 | −0.187 (138) |
| 90+ | +0.069 (18 ⚠) |

There is no monotonic relation, and the 85–89 bucket is the worst. **STRONG stays
disabled.**

## 10. Lower-timeframe (5m) execution of 15m/30m signals

Market-entry HTF signals only. All entries are managed on the same 5m path.

| Set | A5 market at confirmation | D5 first 5m CHoCH | D5b pullback, then 5m BOS/CHoCH |
| --- | --- | --- | --- |
| Baseline 15m (714 signals) | −0.055 (542) | +0.131 (41 ⚠; 89% never get a CHoCH) | −0.063 (186) |
| Baseline 30m (597) | −0.059 (326) | −0.002 (111) | −0.003 (176) |
| Trend 15m (300) | +0.008 (189) | +0.477 (17 ⚠) | +0.117 (64) |
| Trend 30m (249) | +0.121 (121) | +0.081 (41 ⚠) | +0.152 (72) |

- 5m timing raises the per-trade R on some subsets, mostly by **skipping most trades**.
- Samples are mostly below 50 per cell, and total R per HTF signal does not consistently
  improve.
- **No validated LTF execution rule.**
- The distinction stays explicit in code: a 5m event can only time an existing HTF thesis.
  A test enforces that it never precedes the HTF confirmation.

## 11. Funding / open interest

- **Funding.** In the ~3 months OKX provides, only **3 of 7,882** hypotheses occurred with
  |funding| ≥ 0.03%/8h. There is no testable variation, and it covers only W2–W3.
- **Open interest.** Public history is 1H for ~30 days, 5m for ~2 days, 1D for ~180 days.
  That is far too short for walk-forward.
- **Both stay informational only.** Collecting our own funding/OI history from the live
  feed would make a future test possible.

## 12. Order flow (not built)

- The engine has no trade-aggressor (taker buy/sell) data, no depth/imbalance, and no
  liquidation feed.
- On 1m/5m, where structural stops are within a few ticks of noise and most moves are
  liquidity-driven, this is **likely material**: entries and stop placement compete with
  participants who see the book.
- On 15m–1h it matters less than the lack of any predictive signal in the existing
  features (§9).
- Recommended only if low timeframes are ever revisited.

## 13. Candidate selection (pre-registered grid, 64 variants)

The grid crosses families {trend, trend+pullback, no-reversal, all} × score {baseline, s41}
× threshold {65, 70, 75, 80} × regime {all, no range/transitional}.

**0 of 64 passed in any scope.** Walk-forward selection on development data only, and its
out-of-sample result:

| Scope | Selections (W1, W2, W3) | OOS trades | OOS E[R] | PF | Fresh E[R] |
| --- | --- | ---: | ---: | ---: | ---: |
| 5m | trend+pullback t75/t80 | 263 | +0.006 | 1.01 | +0.102 |
| 15m | trend s41 t65 → trend+pullback t80 | 771 | −0.015 | 0.97 | −0.015 |
| 30m | all t80 → trend+pb t80 → trend t75 | 95 ⚠ | −0.111 | 0.83 | −0.139 |
| 1h | trend t70 (3×) | 83 ⚠ | +0.187 | 1.34 | +0.100 |
| 15m–1h | trend+pb t70 → t80 → trend t75 | 617 | +0.023 | 1.04 | −0.036 |

1h trend is the most encouraging scope, but with only **83** out-of-sample trades it is
`INSUFFICIENT_SAMPLE`.

### Exploratory refinement (post-hoc, disclosed)

Retrace entry, runner exit and the not-extended filter each looked better in §8 **on the
validation windows**. A 48-variant trend grid
(entry × exit × filter × threshold 70/75/80 × regime) was then evaluated. Because its
dimensions came from validation, **it cannot count as a clean pass**.

- Development-only walk-forward selection inside it gives:
  - 15m–1h: +0.230 R OOS (n=463, PF 1.41, all windows positive, fresh +0.186)
  - 15m: +0.146
  - 30m: +0.211 (108 ⚠)
  - 5m: −0.003
- **Threshold behaviour:** at 75 every trend variant with retrace or runner is positive in
  all windows. At 70 W3 is always negative. At 80 samples are too small. That is a plateau
  above a cliff, not a single magic number.

The variant development data selected last is `trend | retrace | runner | t75 |
no-weak-regime` = **`wese-trade-research-4.1-c590e82e3a`**. Its robustness matrix:

| Dimension | Values (net E[R], trades) |
| --- | --- |
| Pre-period | **−0.068 (252)** — negative before 2026 |
| W1 / W2 / W3 | +0.431 (108) / +0.374 (91) / +0.150 (96) |
| Validation | +0.322 (295), PF 1.59, max DD 14.7 R, max 8 consecutive losses |
| Timeframe | 15m +0.256 (167) · 30m +0.347 (108) · 1h +0.733 (20 ⚠) |
| 15m by window | +0.391 / +0.332 / **+0.010** |
| Symbol | 8 of 12 positive; HYPE −0.109, NEAR −0.123, XRP −0.078, SUI −0.767 (3 ⚠); every symbol < 50 trades ⚠ |
| Side | long +0.406 (131) · short +0.255 (164) |
| Regime | uptrend +0.373 · downtrend +0.279 · strong_up +0.527 ⚠ · strong_down +0.198 ⚠ |
| Score buckets | 75–79 +0.315 (238) · 80–84 +0.363 (45 ⚠) · 85–89 +0.300 (12 ⚠): flat, not inverted |

**Decision.** Not promoted to `passed_historical` or `forward_test`:
- it is post-hoc;
- it is negative in the pre-period, so its edge so far is specific to one period;
- there is too little per-symbol sample.

It is recorded as `testing` (`RESEARCH_CANDIDATES` in `validation.py`). The honest next
test is **prospective**: evaluate it unchanged on candles after 2026-10-04 (never seen),
aiming for at least 150 trades before any status change.

## 14. Decisions applied

| Item | Decision |
| --- | --- |
| Baseline `f26f636443` | frozen, `unproven`, labelled «تجريبي · غير مُثبت» |
| Directional live signals | 15m, 30m, 1h only (experimental label) |
| 1m | research-only / visual context: structurally unsuitable |
| 5m | research-only: negative in every window, no candidate survived |
| 10m | research-only: anchors only, failed acceptance |
| LIQUIDITY_REVERSAL, BREAKOUT_CONTINUATION | EXPERIMENTAL / DISABLED_FOR_SIGNALS (evaluated and visible, never emitted) |
| STRONG classes | disabled (calibration inverted / flat) |
| Break-even after TP1 | disabled (worse again) |
| Score | kept as a transparency display; documented as non-predictive |
| Funding / OI | informational only |
| Forward-test mode | implemented (status machine, «اختبار مباشر» badge); no strategy qualifies |

## 15. Limitations

- **Contamination.** W2–W3 overlap the inspected Phase 4 holdout for the 3 anchors. Fresh
  symbols carry the verdict.
- **Small universe.** 12 symbols and one market phase (Oct 2025 – Oct 2026 for most
  timeframes). Survivorship in symbol selection.
- **Simulation.** Bar-level simulation (stop-first ambiguity, no intrabar path, no queue
  position for limit fills; retrace/zone limits assume a fill at touch).
- **Funding.** Not modelled in R. Holds average about 20 bars.
- **Fixed plan costs.** Cost scenarios reuse plans built with base costs.
- **Score analysis.** Uses isolated hypotheses (overlapping trades counted
  independently).
- **Multiple testing.** About 170 variants were evaluated in total. Some positive variants
  are expected by chance alone, which is why only clean walk-forward selections count.

## 16. Reproduce

```bash
cd backend
.venv/bin/python -m app.scripts.research_fetch --select   # universe (liquidity only)
.venv/bin/python -m app.scripts.research_fetch            # ~1.5 h, resumable
.venv/bin/python -m app.scripts.run_research --name phase41 --workers 4   # ~5 min after pass 1
.venv/bin/python -m app.scripts.research_refine --name phase41            # exploratory grid
.venv/bin/python -m app.scripts.research_report --name phase41 > phase41.md
```

- Run metadata, config, windows, costs and all aggregates are stored in
  `data/research/reports/phase41.json` and in the `research_runs` table of
  `data/research/candles.sqlite` (run id 5; the exploratory refinement is run
  `phase41-refine`).
- Analysis version `analysis-f8db2d5472`.

