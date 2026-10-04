# Wese Trade — Phase 4.1 Signal Edge Research

> **Purpose.** Determine, scientifically, whether a robust positive-expectancy configuration
> of the signal engine exists. Not to make the numbers look good. A "no robust edge"
> conclusion is a valid outcome. Nothing here is a trading recommendation, and nothing
> places orders.

<!-- RESULTS-SUMMARY -->

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

<!-- DATA-TABLE -->

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

<!-- RESULTS -->
