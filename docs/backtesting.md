# Wese Trade — Backtesting & Historical Validation (Phase 4)

> **Phase 4.1 follow-up:** the research in [`research.md`](research.md) uses expanded data,
> 12 symbols and chronological walk-forward windows (this document's 70/30 holdout is now
> considered contaminated). Read it for the current verdict.

> **Bottom line (honest):** the validated engine version `wese-trade-signal-4.0-f26f636443`
> did **not** show a positive expectancy after costs.
>
> | Split       | Trades | Net expectancy | Profit factor (net) |
> | ----------- | -----: | -------------- | ------------------- |
> | Development |    719 | −0.019 R       | 0.97                |
> | Holdout     |    298 | −0.126 R       | 0.80                |
>
> Before costs the edge is roughly zero (+0.087 R development, −0.008 R holdout). The
> confluence score is **not calibrated**: on the holdout, higher scores did worse. Signals
> are analytical descriptions of rule-based setups and **must not** be treated as
> profitable trade recommendations. Nothing in this document should be read as a claim of
> edge.

---

## 1. What the backtester is

- **Same code as live.** `app/backtesting/runner.replay` feeds candles one at a time into
  the Phase 3 `MarketAnalyzer` and calls `runtime.evaluate_closed` → `SignalEngine.evaluate`
  → `SignalTracker`: exactly the objects the live `SignalService` uses. There is no
  separate "backtest strategy".
- **Sequential, no lookahead.**
  - The execution analyzer only ever sees closed candles up to the evaluated one.
  - Context analyzers (higher timeframes) consume a context candle only once its close time
    is ≤ the execution candle's close time, the same rule live enforces by waiting for
    context candles that close at the same instant.
  - The Phase 3 analyzer's no-lookahead/replay suites still pass.
  - `tests/signals/test_backtest.py` checks that replaying the same candles yields identical
    evaluations and that pass 2 reproduces pass 1.
- **Two passes.**
  1. `replay` records every evaluation that had a plan (pass 1, expensive, cached as
     `data/backtests/<name>.pass1.pkl`).
  2. `simulate` re-runs the tracker over the recorded evaluations with a different
     classification config (threshold, cost floor, families, break-even). It is used for
     the grid. With the same config it reproduces pass 1 exactly: this is tested on a
     fixture and verified on the full final dataset.
- **Results in R only.** No account balance, position size or leverage. Every trade risks
  1 R (entry → stop).

## 2. Data

OKX USDT perpetuals, public `history-candles` (paged, 100/request), stored as gzip CSV in
`backend/data/history/` (not committed). 10m is aggregated from 5m exactly like live.

| TF  | Candles per symbol | Range (UTC)             |
| --- | -----------------: | ----------------------- |
| 1m  |             86,400 | 2026-08-05 → 2026-10-04 |
| 5m  |             51,840 | 2026-04-07 → 2026-10-04 |
| 10m |             25,919 | 2026-04-07 → 2026-10-04 |
| 15m |             35,040 | 2025-10-04 → 2026-10-04 |
| 30m |             35,040 | 2024-10-04 → 2026-10-04 |
| 1h  |             26,280 | 2023-10-05 → 2026-10-04 |

Symbols: BTCUSDT, ETHUSDT, SOLUSDT, so 18 series in total. SOL 1m has one missing candle
(86,399).

Context timeframes follow the Phase 3 MTF map (e.g. 15m → 1h, 4h); higher-timeframe history
is fetched to cover each execution range plus warm-up.

**Split:** per series, the first **70 % of time is development**, the last **30 % is
holdout**. A signal belongs to the split of its confirmation time. The holdout was not used
to choose weights, thresholds or rules, with one disclosed exception (§5).

## 3. Costs

| Item      | Value           | Applied to                                 |
| --------- | --------------- | ------------------------------------------ |
| Taker fee | 0.05 % per side | market entries, stops, time/opposite exits |
| Maker fee | 0.02 % per side | zone (limit) entries, take-profits         |
| Slippage  | 0.02 % adverse  | market entries, stops, time/opposite exits |

- **Gross R** = price move in R relative to the planned entry, before any cost.
- **Net R** = after fees and slippage.

The average cost per trade was **0.149 R**, and it varies sharply by timeframe:

| TF           | 1m   | 5m   | 10m  | 15m  | 30m  | 1h   |
| ------------ | ---- | ---- | ---- | ---- | ---- | ---- |
| Average cost | .253 | .226 | .195 | .145 | .107 | .065 |

This is why low timeframes need a fee-aware risk floor (§5).

**Conservative assumptions:**

- On a fill candle only the stop is checked.
- Same-candle stop + target counts as the stop (2 such trades, all in development).
- A gap through the stop exits at the open.
- Funding is not modelled; hold time averages about 22 bars.

## 4. Baseline (before any tuning)

Threshold 70, STRONG at 85, cost floor 3× round trip:

| Split       | Trades | Gross E[R] | Net E[R] |   PF |
| ----------- | -----: | ---------: | -------: | ---: |
| Development |  1,669 |     +0.016 |   −0.133 | 0.79 |
| Holdout     |    673 |     −0.061 |   −0.223 | 0.67 |

Calibration was not monotonic. Diagnostics showed:

- individual components had no meaningful discriminative power (terciles of each
  component's value vs R were flat);
- costs consumed the small gross edge;
- low-timeframe stops were too tight relative to fees.

## 5. Adjustments (development split only) and why

A grid of 24 variants was evaluated with pass 2 on the **development split only**:
threshold {70, 75, 80} × cost floor {3, 5} × break-even after TP1 {off, on} ×
liquidity reversal {on, off}.

| thr | cost× | BE  | reversal |    n | net E[R] | gross E[R] |   PF | DD (R) | +symbols/3 | +TFs/6 |
| --: | ----: | --- | -------- | ---: | -------: | ---------: | ---: | -----: | ---------: | -----: |
|  80 |     5 | off | on       |  234 |   +0.051 |     +0.140 | 1.09 |   16.9 |          1 |      2 |
|  80 |     5 | off | off      |  231 |   +0.046 |     +0.135 | 1.08 |   16.9 |          1 |      2 |
|  80 |     5 | on  | on       |  234 |   +0.009 |     +0.099 | 1.02 |   15.7 |          1 |      2 |
|  75 |     5 | off | on       |  572 |   +0.007 |     +0.098 | 1.01 |   46.9 |          1 |      2 |
|  75 |     5 | off | off      |  556 |   +0.004 |     +0.096 | 1.01 |   46.3 |          1 |      2 |
|  70 |     5 | off | off      |  955 |   −0.021 |     +0.068 | 0.96 |   65.6 |          1 |      3 |
|  80 |     3 | off | on       |  362 |   −0.067 |     +0.069 | 0.89 |   32.1 |          2 |      0 |
|  75 |     3 | off | off      |  920 |   −0.116 |     +0.031 | 0.82 |  110.2 |          0 |      0 |
|  70 |     3 | off | on       | 1669 |   −0.133 |     +0.016 | 0.79 |  231.6 |          0 |      1 |
|  70 |     3 | on  | on       | 1746 |   −0.167 |     −0.017 | 0.72 |  301.9 |          0 |      0 |

(10 of 24 rows shown.)

- The grid replays the **baseline** pass 1, which was built at a 3× floor. A 5× row
  therefore approximates the final config by **rejecting** plans below 5×, whereas the
  final engine **widens** such stops. This is why the final trade counts differ from the
  grid.
- A pass-2 tolerance bug was fixed during documentation: tick rounding of zone-entry
  midpoints made pass 2 drop about 1 % of floor-widened plans. The 3× rows above are the
  corrected values, and the conclusions are unchanged.
- Pass 2 now reproduces the final pass 1 exactly on the full dataset (719 / 298 trades).

**Decisions:**

- **Cost floor 5×** improved **every** variant. This is a structural fix: a trade whose
  risk is not at least 5× the round-trip cost cannot overcome its costs.
- **Break-even after TP1 off.** It hurt every variant, because it converts many trades that
  later reach TP2 into scratches.
- **Threshold 75, not 80.** 80/5× was the best development row (+0.051 R), but positive on
  only 1 of 3 symbols and 2 of 6 timeframes, with n = 234: a fragile, likely overfit
  optimum. 75 keeps 2.4× more trades with a similar profile.
- **Liquidity reversal kept.** Removing it changed little, and removing a family because of
  34 trades would be curve-fitting.
- **STRONG disabled. Disclosure:** this used holdout information. On the holdout, the 85+
  bucket was worse than 75–84. The choice is conservative (it removes a claim rather than
  adding performance), but it is still holdout-informed and is reported as such.

No weights, penalties or rules were tuned against the holdout.

## 6. Final canonical run

`python -m app.scripts.run_backtest --name final --save-db` (version `f26f636443`,
generated 2026-10-04). Gross = before costs; DD = maximum drawdown in R.

### Overall

| Split       | Trades | Win rate | Gross E[R] | Net E[R] | PF (net) | Max DD (R) | Median R | TP1 / TP2 / TP3       | Max losing streak |
| ----------- | -----: | -------: | ---------: | -------: | -------: | ---------: | -------: | --------------------- | ----------------: |
| Development |    719 |    39.6% |     +0.087 |   −0.019 |     0.97 |       48.0 |   −0.494 | 48.5% / 28.8% / 18.8% |                12 |
| Holdout     |    298 |    34.6% |     −0.008 |   −0.126 |     0.80 |       47.5 |   −1.034 | 45.6% / 24.8% / 17.8% |                13 |
| All         |  1,017 |    38.1% |     +0.059 |   −0.050 |     0.92 |       52.9 |   −0.510 | 47.7% / 27.6% / 18.5% |                12 |

- Expired (no fill): 22.
- Invalidated: 0.
- Ambiguous same-candle trades: 2 (development).
- Average hold: 21.8 bars.
- STRONG signals: 0, by design.

### By symbol (net E[R], trades)

| Symbol  | Development  | Holdout      | All          |
| ------- | ------------ | ------------ | ------------ |
| BTCUSDT | +0.135 (186) | −0.160 (79)  | +0.047 (265) |
| ETHUSDT | −0.055 (233) | −0.143 (85)  | −0.078 (318) |
| SOLUSDT | −0.086 (300) | −0.096 (134) | −0.089 (434) |

BTC was the only positive symbol in development, and it turned negative on the holdout.

### By timeframe (net E[R], trades)

| TF  | Development  | Holdout     | All          |
| --- | ------------ | ----------- | ------------ |
| 1m  | −0.116 (6)   | −0.492 (3)  | −0.241 (9)   |
| 5m  | −0.042 (70)  | −0.324 (39) | −0.142 (109) |
| 10m | +0.075 (77)  | −0.126 (33) | +0.015 (110) |
| 15m | −0.024 (197) | −0.095 (73) | −0.043 (270) |
| 30m | −0.007 (256) | −0.251 (96) | −0.074 (352) |
| 1h  | −0.080 (113) | +0.216 (54) | +0.015 (167) |

- 1m almost never trades: its ATR is too small relative to costs, so the cost floor
  exceeds the 3 ATR ceiling. That is intended; 1m signals are not viable after fees.
- 1h is positive on the holdout but negative in development: there is no consistent
  timeframe edge.

### By setup family (net E[R], trades)

| Family                | Development  | Holdout         | All          |
| --------------------- | ------------ | --------------- | ------------ |
| TREND_CONTINUATION    | +0.028 (162) | **+0.091 (65)** | +0.046 (227) |
| BREAKOUT_CONTINUATION | −0.031 (334) | −0.151 (122)    | −0.063 (456) |
| PULLBACK_CONTINUATION | −0.024 (201) | −0.176 (99)     | −0.074 (300) |
| LIQUIDITY_REVERSAL    | −0.130 (22)  | −0.633 (12)     | −0.307 (34)  |

TREND_CONTINUATION is the **only family positive in both splits**. It was **not** adopted
as the only enabled family: that would select on the holdout, and n = 65 is small. It is
recorded as a **hypothesis for forward testing**, not a result.

### By regime at signal time (net E[R], trades)

| Regime           | Development  | Holdout      | All          |
| ---------------- | ------------ | ------------ | ------------ |
| strong_uptrend   | −0.038 (58)  | +0.263 (38)  | +0.081 (96)  |
| uptrend          | −0.175 (217) | −0.154 (126) | −0.167 (343) |
| range            | −0.138 (53)  | −0.244 (29)  | −0.175 (82)  |
| transitional     | −0.146 (24)  | −0.254 (15)  | −0.188 (39)  |
| downtrend        | +0.123 (283) | −0.240 (70)  | +0.051 (353) |
| strong_downtrend | +0.029 (84)  | −0.024 (20)  | +0.019 (104) |

Range and transitional regimes are negative in both splits, as expected for structure
continuation logic. The `uptrend` regime is consistently negative, but there is no
justification yet for regime-specific rules.

## 7. Score calibration and robustness

Net E[R] (trades) by score bucket. No signals scored below 75 (the threshold) and none
scored 95–100.

| Score | Development  | Holdout      | All          |
| ----- | ------------ | ------------ | ------------ |
| 75–79 | −0.049 (458) | −0.060 (190) | −0.052 (648) |
| 80–84 | −0.000 (210) | −0.195 (85)  | −0.056 (295) |
| 85–89 | +0.195 (39)  | −0.345 (21)  | +0.006 (60)  |
| 90–94 | +0.095 (12)  | −1.126 (2)   | −0.080 (14)  |

- **Development:** roughly increasing (monotonic flag true).
- **Holdout:** **inverted**. Higher scores did worse.

The score therefore does **not** carry reliable information about outcome quality. It is
displayed only as a confluence measure (`NN/100`), never as a probability. The STRONG tier
stays disabled.

**Robustness verdict:**

- The development → holdout drop (−0.019 → −0.126 R) is larger than the development
  standard error (about ±0.05 R).
- Sub-group results flip sign between splits.
- Calibration inverts.

There is **no robust edge**. The system is not deployment-quality as a signal generator.

## 8. Known weaknesses

1. **No demonstrated edge after costs**; gross edge ≈ 0 on the holdout.
2. **Uncalibrated score.** The confluence components showed no discriminative power.
3. **Costs dominate low timeframes** (0.19–0.25 R per trade on 1m–10m).
4. **Bar-level simulation.** No intrabar path or order-book depth; queue position for limit
   fills is ignored; fills at the limit are assumed.
5. **Regime coverage.** 1m/5m/10m span only 2–6 months; 1h spans 3 years. Holdout periods
   differ per timeframe.
6. **No funding, open interest, order flow or news.** By design for Phase 4; news is never
   an input.
7. **Small family samples** (reversal n = 34); STRONG unvalidated.
8. **Multiple testing.** 24 grid variants on one development split; the chosen config is
   still subject to selection bias, which the holdout result reflects.

## 9. How to reproduce

```bash
cd backend
.venv/bin/python -m app.scripts.fetch_history            # ~12 MB into data/history (public OKX data)
.venv/bin/python -m app.scripts.run_backtest --name final --workers 4 --save-db
```

- The report is written to `data/backtests/final.json`; pass 1 is cached.
- `--save-db` stores the run in `backtest_runs`, which is visible at `/backtests`
  (admin/analyst).
- The `strategy_version` in the report must match the code you are running.
