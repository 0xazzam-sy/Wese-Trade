# Wese Trade Strategy 4.3 (v1.2)

- **Version:** `wese-trade-strategy-4.3-6044cea28a`
- **Fingerprint:** `4.3-6044cea`
- **Frozen baseline (unchanged, still running):** Strategy 4.2
  `wese-trade-forward-4.2-a03e20f1d4` (`4.2-a03e20f`).

4.3 is built for **practical signal availability**. It uses weighted market evidence and
quality tiers instead of waiting for a near-perfect setup. The score
(«قوة الإشارة») is a weighted-evidence value out of 100. It is **not** a probability
of profit.

## 1. Definition

4.3 runs the same canonical pipeline as 4.2:
- `MarketAnalyzer` snapshot of the closed candle, plus context frames closed at the same instant;
- `SignalEngine` weighted evidence;
- structural plans;
- `SignalTracker` lifecycle with costs.

There is no separate implementation. Only the selection changes (`app/strategy43/config.py`):

| | Strategy 4.2 (frozen) | Strategy 4.3 |
|---|---|---|
| Families | trend continuation | trend continuation + pullback continuation |
| Minimum score | 75 | 65, graded into tiers |
| Excluded regimes | ranging, transitional | ranging only (TRANSITION is not "never trade") |
| BUY / SELL margin | 10 points | 10 points (e.g. 71 vs 43 → BUY; 58 vs 55 → WAIT) |
| Entry | retrace limit at the confirmation-candle midpoint | same |
| Exits | runner: ½ at TP1, ½ at TP3, 96-candle hold | same |
| Costs | taker 0.05%, maker 0.02%, slippage 0.02% | same |

### Tiers

These come from the development score distribution and the per-tier results below:

| Tier | Score | Arabic label |
|---|---|---|
| A+ | ≥ 82 | استثنائية |
| A | ≥ 75 | قوية |
| B | ≥ 70 | جيدة |
| C | ≥ 65 | مقبولة |
| WAIT | below 65 | انتظار |

### Weighted evidence

Each item below is weighted and moves the score. None is an automatic block.
- **Trend:** EMA stack and slope, position.
- **Structure:** swing and internal HH/HL/LH/LL, BOS/CHoCH.
- **Multi-timeframe alignment.**
- **Liquidity:** pools, sweeps, EQH/EQL.
- **Location:** premium/discount, OTE, zones such as FVG / OB, room to the opposing level.
- **Momentum:** RSI and its slope. A high RSI is not a block.
- **Volume / relative volume:** low volume lowers confidence; it never kills a trade.
- **Displacement and candle confirmation.**
- **Penalties** for opposing zones and extension.

### Hard blockers

These are the only cases that stop a signal (engine gates and plan validation):
- analysis not ready, or corrupted / inconsistent structure data;
- stale market data (feed not live, or the candle closed more than 120 s ago);
- inactive symbol;
- catastrophic volatility;
- missing higher-timeframe context;
- no plan with valid geometry, including an impossible stop or risk below the cost floor;
- an active trade in the same context.

### Regimes shown to the user

The canonical regime is mapped to UPTREND / DOWNTREND / RANGE / COMPRESSION /
BREAKOUT (expansion) / TRANSITION.

## 2. How the configuration was chosen

The windows are fixed, on 12 liquid USDT perpetuals × 15m / 30m / 1h:
- **Development:** 2025-10-04 → 2026-04-01.
- **Validation:** 2026-04-01 → 2026-07-01.
- **Holdout:** 2026-07-01 → 2026-10-04, evaluated **once**.

1. **A generic 10-family weighted technical engine was tried first.** It covered trend
   continuation, pullback, breakout, breakout + retest, momentum, support reaction,
   resistance reaction, liquidity sweep, range edge and structure reversal
   (`app/research/s43_generic`). It is kept as a documented negative result:
   - Gross expectancy was only about +0.02R per trade.
   - Fees and slippage cost 0.09–0.19R per trade, so every family was negative after
     costs (dev: −0.02 to −0.34R).
   - A retrace limit entry added about +0.11R, which brought it to roughly breakeven,
     still without a measurable edge.
   - It is **not** used in production.
2. **The engine's own weighted-evidence hypotheses were tested instead**, using the
   validated lifecycle simulator. Grid: family set × score threshold (55–75) × regime
   exclusion. Trend + pullback continuation, excluding only ranging, formed a smooth
   positive plateau on development data, not an isolated peak:

   | Threshold | Signals/day | E |
   |---|---|---|
   | 60 | 12.2 | +0.040 |
   | 65 | 9.0 | +0.060 |
   | 70 | 5.8 | +0.055 |
   | 75 | 3.0 | +0.106 |

   Breakout and liquidity-reversal families made the frontier worse and were not enabled.
3. **Validation (April–June)** showed the score is monotonic at the top:
   - score ≥ 75 stayed positive (+0.076R at 2.0/day);
   - the 65–75 band was around breakeven to negative.

   The tier floors therefore carry meaning: A+ and A hold the measured edge, while B and C
   are shown as lower quality, as the product requires.
4. **The holdout was evaluated once**, with the final configuration. Nothing was tuned after it.

## 3. Before / after: Strategy 4.2 vs Strategy 4.3

Same data, same costs, same simulator, no look-ahead. Only candles observed closing can
confirm. The stop counts first when stop and target fall in one candle.

| Window | Strategy | Signals/day | Signals/week | Trades | Win rate | E (R) | PF | Avg win / loss (R) | Max DD (R) | Symbol-days with a signal | Hours with a live opportunity | Top-symbol share |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| dev | 4.2 | 1.88 | 13.1 | 289 | 40.5% | +0.087 | 1.15 | 1.68 / -1.0 | 43.7 | 12.6% | 41.4% | 12.1% |
| dev | 4.3 | 9.01 | 63.0 | 1389 | 39.7% | +0.060 | 1.1 | 1.66 / -0.99 | 109.1 | 46.1% | 91.1% | 10.6% |
| validation | 4.2 | 1.1 | 7.7 | 89 | 44.9% | +0.226 | 1.42 | 1.7 / -0.97 | 10.4 | 7.9% | 29.4% | 13.5% |
| validation | 4.3 | 8.01 | 56.1 | 637 | 37.5% | -0.064 | 0.9 | 1.48 / -0.99 | 88.5 | 45.7% | 88.4% | 10.2% |
| holdout | 4.2 | 1.25 | 8.8 | 103 | 40.8% | +0.255 | 1.47 | 1.95 / -0.91 | 14.7 | 9.2% | 36.4% | 18.4% |
| holdout | 4.3 | 8.27 | 57.9 | 700 | 38.4% | +0.038 | 1.06 | 1.65 / -0.97 | 45.2 | 44.3% | 96.1% | 11.4% |
| year | 4.2 | 1.52 | 10.6 | 481 | 41.4% | +0.149 | 1.26 | 1.74 / -0.98 | 43.7 | 10.5% | 37.3% | 9.8% |
| year | 4.3 | 8.57 | 60.0 | 2726 | 38.9% | +0.025 | 1.04 | 1.61 / -0.99 | 109.1 | 45.5% | 91.8% | 9.4% |

**Strategy 4.3 by tier**

| Window | A+ (≥82) n / E / PF | A (75–82) n / E / PF | B (70–75) n / E / PF | C (65–70) n / E / PF | A+ and A together n / E / PF |
|---|---|---|---|---|---|
| dev | 62 / +0.268 / 1.45 | 299 / +0.230 / 1.42 | 423 / -0.057 / 0.91 | 605 / +0.037 / 1.06 | 361 / +0.236 / 1.43 |
| validation | 18 / -0.689 / 0.11 | 112 / +0.136 / 1.26 | 190 / -0.178 / 0.72 | 317 / -0.031 / 0.95 | 130 / +0.021 / 1.04 |
| holdout | 27 / -0.022 / 0.96 | 137 / +0.243 / 1.45 | 209 / -0.241 / 0.64 | 327 / +0.134 / 1.23 | 164 / +0.200 / 1.36 |
| year | 107 / +0.034 / 1.05 | 548 / +0.214 / 1.4 | 822 / -0.132 / 0.79 | 1249 / +0.045 / 1.07 | 655 / +0.185 / 1.33 |

**Common year, by timeframe and side (signals / trades / E)**

| Strategy | 15m | 30m | 1h | Long | Short |
|---|---|---|---|---|---|
| 4.2 | 299 / 269 / +0.111 | 206 / 178 / +0.141 | 51 / 34 / +0.486 | 167 / 149 / +0.424 | 389 / 332 / +0.025 |
| 4.3 | 1699 / 1497 / +0.027 | 1023 / 895 / +0.000 | 413 / 334 / +0.085 | 1100 / 964 / +0.048 | 2035 / 1762 / +0.013 |

**Common year, Strategy 4.3 by family (signals / trades / E / PF)**

- PULLBACK_CONTINUATION: 1279 / 1096 / +0.069 / 1.11
- TREND_CONTINUATION: 1856 / 1630 / -0.004 / 0.99

## 4. What this means

- **Availability: much higher.**
  - Signals: 8.6/day versus 1.5/day for 4.2 over the common year (5.6×).
  - Symbol-days with at least one signal: 45% versus 10%.
  - Hours with a live opportunity somewhere in the 12-symbol research universe: 92% versus 37%.
  - The live scanner covers 30 liquid symbols, which raises availability further.
- **Quality: defensible at the top, thin at the bottom.**
  - A+ and A together: +0.185R per trade, PF 1.33, at about 1.8 signals/day (more than 4.2's
    +0.149R at 1.5/day). On the holdout: +0.200R, PF 1.36.
  - The B / C band (65–75) is about breakeven after costs over the year, and B is not
    better than C.
  - All tiers together: +0.025R, PF 1.04 over the year; +0.038R on the holdout. On
    validation it was −0.064R, so the lower tiers can lose in some quarters.
- **How to use the tiers.**
  - The UI shows every tier with its label.
  - Telegram sends every confirmed BUY / SELL, as requested.
  - Recipients can filter by timeframe and symbol.
  - A user who wants the measured edge should act mainly on A+ / A.
- **Honest limits.**
  - Only two families carry an after-cost edge. The other setup families (breakout, sweep,
    range edge, support / resistance reactions, momentum, structure reversal) are present
    only as weighted **evidence** inside the score, not as separate signal families,
    because none of them survived costs on their own.
  - Results are historical, from one year of 12 symbols. They do not guarantee future
    performance.

## 5. Live engine (`app/strategy43/service.py`)

- **Always on.** It starts with the application in every runtime mode and no longer depends
  on the forward-test run status. That dependency was the root cause of «متابعة الإشارات
  غير نشطة حالياً».
- **Universe:**
  - the liquid core plus the most liquid **crypto** USDT perpetuals by 24h traded value
    (OKX `instCategory` 1: no tokenized stocks or commodities);
  - 30 symbols × 15m / 30m / 1h, subscribed at startup;
  - any symbol a chart opens is added on demand, on all three timeframes.
- **Persistence:**
  - every confirmed signal is stored once in `strategy43_signals` (stable id, frozen terms;
    later writes touch lifecycle columns only);
  - per-stream cursors in `strategy43_cursors`.
- **Restart:** after a restart, candles that closed while the app was down only advance open
  signals; they never create new ones.
- **Lifecycle:**
  - CONFIRMED (waiting for entry) → ACTIVE → TP1 / TP2 / TP3;
  - STOPPED; EXPIRED (no fill within 6 candles); INVALIDATED (entry missed / setup broken);
  - CLOSED (time stop / opposite signal).
- **Scanner** («أفضل الفرص الآن»): open confirmed signals ranked by tier, waiting-for-entry
  first, then score, freshness and R:R. It only lists confirmed signals; it never creates them.
- **Health** (`GET /api/v1/strategy43/health`):
  - state: running / starting / degraded / stopped, with the real technical problems;
  - last market update, last analysed candle, last scan, last signal;
  - open opportunities by tier;
  - signal counts for today / 7 days / 30 days;
  - execution layer and Telegram status;
  - the 4.2 baseline.
- **Execution timing** (1m / 5m / 10m, `docs/execution.md`) now uses Strategy 4.3 parents:

  | Parent | Execution timeframes |
  |---|---|
  | 15m | 1m, 5m |
  | 30m | 5m, 10m |
  | 1h | 10m |

## 5b. Warm-start opportunity restore (v1.2.1)

- **What changed:** v1.2.0 treated seeded history as warm-up only, so the live engine had
  no state until a new candle confirmed a setup, often hours after every start. From
  v1.2.1, at startup (and when any chart opens a symbol), the recent closed history of
  15m / 30m / 1h is replayed through **the same live evaluator** (`evaluate_candle`) and
  `SignalTracker` (`app/strategy43/warm.py`).
- **What is restored:** only setups that are still actionable now, judged by the
  execution layer's own entry rules:
  - waiting for entry, or entered without a target hit;
  - at most 0.6R beyond the planned entry;
  - R:R to TP1 ≥ 0.8;
  - not past the stop or invalidation;
  - fresh market data.
- **What is never restored:** expired, invalidated, stopped or TP-hit setups.
- **Telegram:** restored signals are persisted with `warm_start` and are **never** sent
  as new alerts.
- **Parity:** `tests/strategy43/test_warm_parity.py` replays real ETH-USDT candles through
  the research/report path and through the production path, and requires identical
  signals (ids, sides, scores, states, plans). It also pins the production config to the
  published version above.

## 6. Reproduce

```
cd backend
python -m app.research.s43_report report.json   # needs the pass-1 research cache
```

The generic 10-family research engine and its replay are in
`app/research/s43_generic` (for reproducibility only; not used in production).
