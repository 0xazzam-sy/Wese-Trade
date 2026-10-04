# Wese Trade — Signal Engine (Phase 4)

> **Analytical only.** Wese Trade never places orders, never connects exchange accounts,
> never uses leverage and never uses an LLM to predict markets. A signal is a description of
> a rule-based setup with a structural trade plan. It is **not** a recommendation and
> **not** a guarantee: «الإشارات تحليلية وليست ضماناً للربح.»
>
> **Read [`research.md`](research.md) and [`backtesting.md`](backtesting.md) before trusting any
> signal.** The strategy is labelled «تجريبي · غير مُثبت» in the UI. The historical
> validation of this engine version did **not** demonstrate a positive expectancy after
> costs (holdout −0.126 R per trade).

---

## 1. Architecture

```
MarketDataEngine ─► AnalysisService (Phase 3 MarketAnalyzer per stream, unchanged)
                          │ AnalysisListener: on_seeded / on_closed / on_forming
                          ▼
                    SignalService (app/signal_engine/service.py)        live only
                          │ waits for context timeframes closing at the same instant
                          ▼
   runtime.evaluate_closed / evaluate_developing (app/signal_engine/runtime.py)   ◄── shared
                          │ builds SignalInput from analyzer snapshots (exec + MTF)
                          ▼
   SignalEngine.evaluate(SignalInput) -> SignalEvaluation        PURE, deterministic
       gate → triggers → setup families → bull & bear scores → class → trade plan
                          ▼
   SignalTracker (lifecycle.py)   dedupe, cooldown, confirmation, fills, TP/SL, expiry
                          ▼
   signal.* WebSocket events · signals / signal_outcomes tables · REST
```

- **One engine.** `SignalEngine.evaluate` is a pure function of a `SignalInput` (analysis
  snapshot of the execution timeframe, context-timeframe snapshots, recent bars, symbol
  metadata, stale flag). No network, no clock, no randomness. Live, replay and the
  backtester all call it through `runtime.py`, and the backtester drives the same
  `SignalTracker`. A future scanner must do the same.
- **The Phase 3 analysis engine was not rewritten.** It is consumed through
  `AnalysisService` accessors (`analyzer`, `forming`, `context_frames`) and a listener hook.
- **Config & version.** Every weight/threshold lives in `app/signal_engine/config.py`.
  `strategy_version()` = `wese-trade-signal-4.0-<sha256(signal config + analysis config)[:10]>`
  is stored with every evaluation, signal and backtest run. The validated version is
  **`wese-trade-signal-4.0-f26f636443`**.

## 2. Classes

| Class         | Arabic   | Condition                                                         |
| ------------- | -------- | ----------------------------------------------------------------- |
| `STRONG_BUY`  | شراء قوي | score ≥ strong threshold **and** `strong_enabled` (currently off) |
| `BUY`         | شراء     | best long hypothesis score ≥ 75, spread ≥ 10, valid plan          |
| `NEUTRAL`     | محايد    | anything else (with an Arabic reason)                             |
| `SELL`        | بيع      | mirror of BUY                                                     |
| `STRONG_SELL` | بيع قوي  | mirror of STRONG_BUY (currently off)                              |

`strong_enabled = False`: on the holdout the 85+ bucket performed **worse** than 75–84
(see backtesting.md §6), so evidence does not support a "strong" tier. The classes stay in
the contract; the engine simply never emits them in this version.

**NEUTRAL is the default.** A missing trigger, a failed gate, a conflict, a weak score or a
plan that cannot be built all produce NEUTRAL with the reason shown to the user.

## 3. Eligibility gate (`engine._gate`)

Evaluation stops with NEUTRAL when any of these holds:

1. analysis not ready (insufficient history, warm-up);
2. market data stale (`market.stream` ≠ `live`), never evaluated on stale data;
3. symbol inactive / not tradable;
4. ATR percentile ≥ 99 (extreme volatility);
5. first higher timeframe not ready (`require_htf_context`);
6. inconsistent swing protected level (data sanity check);
7. **no trigger**: no structure event confirmed on the evaluated candle.

## 4. Triggers and setup families (`rules.py`)

Every hypothesis starts from **one structure event confirmed on the evaluated candle**
(developing evaluations use developing breaks on the forming candle). This gives every
signal an identifiable trigger id (dedupe) and makes "confirmed at candle close" exact.

Long side shown; shorts mirror.

| Family                  | Trigger                         | Requires                                                                                      | Stop anchors (priority)                                          | Entry                                                       |
| ----------------------- | ------------------------------- | --------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- | ----------------------------------------------------------- |
| `TREND_CONTINUATION`    | internal bullish BOS            | swing structure bullish; EMA trend not bearish; regime not bearish/range                      | internal protected low, swing protected low                      | MARKET                                                      |
| `PULLBACK_CONTINUATION` | internal bullish CHoCH          | swing bullish; pullback reached value (discount / OTE / OB / FVG); regime not bearish         | pullback extreme, internal/swing protected low                   | ZONE if a supporting zone edge is within 1 ATR, else MARKET |
| `BREAKOUT_CONTINUATION` | swing bullish BOS               | displacement ≥ 50; relative volume ≥ 1.2; close location ≥ 0.5; no HTF `strong_downtrend`     | internal protected low, breakout candle low, swing protected low | MARKET                                                      |
| `LIQUIDITY_REVERSAL`    | bullish CHoCH (or internal BOS) | sell-side sweep ≤ 10 bars ago; price back above the swept level; sweep low not undercut since | sweep extreme, internal protected low                            | MARKET                                                      |

Rejections are kept as Arabic reasons (e.g. «استمرار الاتجاه: الهيكل الرئيسي غير متوافق»);
with no trigger at all the reason is «لا توجد فرصة واضحة».

## 5. Scoring (`scoring.py`)

Bull and bear are scored **independently**: each side's best hypothesis (family × trigger)
gets a score. Components are 0..1 values multiplied by category weights:

| Category       | Weight | Measures                                                                                                                                      |
| -------------- | -----: | --------------------------------------------------------------------------------------------------------------------------------------------- |
| `htf`          |     20 | trend + structure agreement of the ready higher TFs (weights 0.6 / 0.4)                                                                       |
| `structure`    |     20 | swing (0.6) and internal (0.4) direction; +0.2 for a recent aligned swing CHoCH; reversals against swing get 0.25 instead of 0                |
| `liquidity`    |     15 | aligned recent sweep (more if structure responded); target liquidity within 4 ATR ahead                                                       |
| `location`     |     15 | breakouts: distance from EMA (not over-extended); others: discount/premium + OTE (capped 0.45 together) + touched supporting OB / FVG quality |
| `trend`        |     10 | EMA trend score and stack in the trade direction                                                                                              |
| `displacement` |      7 | trigger candle displacement                                                                                                                   |
| `volume`       |      5 | trigger relative volume                                                                                                                       |
| `momentum`     |      5 | RSI level / slope agreement                                                                                                                   |
| `candle`       |      3 | close location / body of the trigger candle                                                                                                   |

Components are clamped to 0..1 before weighting.

**Double-counting defence.**

- `displacement + volume + candle` all describe the same trigger candle. Their weights are
  rescaled so the cluster can contribute at most **10** points.
- Discount/premium and OTE describe the same retracement and are capped together (0.45).
- The score is normalised over the **available** categories: 1h has no higher timeframe,
  so `htf` is excluded rather than counted as zero.

`score = clamp(100 · points / available_weight − penalties, 0, 100)`

### Penalties (conflict defence)

| Code                    |                                                   Points | When                                                                      |
| ----------------------- | -------------------------------------------------------: | ------------------------------------------------------------------------- |
| `htf_strong_opposition` | 15 (8 for a reversal with an aligned recent swing CHoCH) | a ready higher TF is in a strong opposite trend                           |
| `htf_first_opposed`     |                                                        8 | otherwise: first higher TF has opposite trend **and** structure           |
| `extreme_location`      |                                                        8 | long at ≥ 85% of the premium/discount range (short ≤ 15%); not breakouts  |
| `overextended`          |                                                        6 | price > 3 ATR from the EMA                                                |
| `extreme_volatility`    |                                                        6 | volatility regime `extreme`                                               |
| `volume_contradiction`  |                                           4 (8 breakout) | trigger relative volume < 0.6                                             |
| `momentum_opposed`      |                                                        5 | side-adjusted RSI < 40 and RSI slope against the trade                    |
| `opposite_divergence`   |                                                        4 | RSI divergence against the trade                                          |
| `adverse_sweep`         |                                                        6 | a sweep against the trade within 5 bars                                   |
| `opposing_zone_ahead`   |                                                        5 | active/mitigated opposing order block (quality ≥ 40) within 0.5 ATR ahead |
| `transitional_regime`   |                                                        4 | regime transitional (trend/pullback families)                             |

### Classification

```
best_bull, best_bear = best hypothesis score per side (0 if none)
chosen = the higher side;  top = its score;  spread = top − other
if top < 75                              → NEUTRAL «الأدلة ضعيفة — لا توجد فرصة واضحة»
elif spread < 10                         → NEUTRAL «أدلة متعارضة بين الشراء والبيع»
if chosen score ≥ 40: plan = build_plan  (a rejection → NEUTRAL with the plan reason)
class = STRONG_* if strong_enabled and top ≥ 85 else BUY/SELL
```

Hypotheses ≥ 40 get a plan even when NEUTRAL, so the details drawer can show what the
engine considered. Only a non-NEUTRAL closed-candle evaluation can become a signal.

**The score is confluence, not probability.** The UI shows «قوة الإشارة 78/100», never a
percentage and never «احتمال النجاح». The backtest shows the score is **not calibrated**:
on the holdout, higher buckets did worse.

## 6. Developing vs confirmed

- **Developing**: the forming candle is evaluated (throttled, `developing_min_interval_seconds
= 5`, published only when class/score changes or while non-NEUTRAL) as `signal.developing`.
  It is never a trade: no tracker, no persistence, no plan lines on the chart. The UI says
  «شراء — قيد التشكّل» with an amber pulse.
- **Confirmed**: only an evaluation of a **closed** candle can create a signal. Live waits for
  the context timeframes that close at the same instant (≤ 15 s), so live sees exactly what
  the backtest saw.
- **Seed evaluation** (display only): when a stream is first opened, the last seeded candle
  is evaluated so the panel is not blank. It never reaches the tracker, and a non-NEUTRAL
  result is withheld because no live signal was issued for that candle.

## 7. Cooldown and dedupe (`lifecycle.py`)

- `signal_id = sha256(symbol | timeframe | family | side | trigger_id)`: stable, so the
  same trigger can never produce two signals (also across restarts: recent ids are loaded
  from the database on seed).
- Same-side cooldown: 5 candles after a confirmation. Opposite side within the cooldown is
  suppressed unless STRONG (never, while STRONG is disabled).
- While a signal is open, a new same-side signal is suppressed (`active_same_side`); an
  opposite non-STRONG one is suppressed (`active_opposite`).
- Suppression counts are exposed in `/signals/health` and every backtest report.

## 8. Trade plan (`trade_plan.py`)

All prices are rounded to the instrument tick.

**Entry.**

- `MARKET_ENTRY`: entry = the confirmation candle close (`entry_low = entry_high = preferred`).
- `ZONE_ENTRY` (pullbacks with a supporting zone edge ≤ 1 ATR away): `entry_low/high` span
  the zone edge and the close; `preferred_entry` (their midpoint) is the limit price.

**Stop (structure-aware).**

- The first anchor on the risk side of price (see §4), minus a buffer of
  `max(3 ticks, 0.1 ATR)`.
- Risk floor = `max(0.5 ATR, 5 ticks, 5 × round-trip cost × price)`. A stop tighter than the
  floor is **widened** to it: tiny stops on low timeframes made fees dominate the result.
  If the floor itself exceeds the ceiling (very low ATR relative to costs, typical on 1m)
  the plan is rejected («وقف الخسارة المنطقي أصغر من تكلفة التداول والضوضاء»).
- Risk ceiling = 3 ATR. An anchor farther than that is skipped and the next anchor tried;
  if none fits the plan is rejected («لا يوجد وقف خسارة منطقي ضمن الحدود»). Stops are
  never compressed.
- `invalidation` = the structural level itself. A close beyond it before the fill
  invalidates the signal.

**Targets (structural).**

- Candidates on the reward side:
  - liquidity pools (EQH/EQL, swing highs/lows)
  - swing/internal break levels
  - opposing OB/FVG near edges
  - the range extreme
- Each candidate is front-run by `max(tick, 0.05 ATR)`.
- Candidates within 0.3 R of each other are merged; anything beyond 8 R is discarded.
- TP1 = the first structural candidate between 0.75 R and 2 R, otherwise a 1 R extension.
- TP2 = first candidate ≥ max(TP1 + 0.4 R, 1.5 R), else an extension at max(2 R, TP1 + 0.75 R).
- TP3 = first candidate ≥ max(TP2 + 0.5 R, 2 R), else an extension at max(3 R, TP2 + 1 R).
- Targets are strictly ordered and distinct; each carries its `source`.
- Headroom gate: opposing structure closer than 0.75 R to the entry rejects the plan
  («مستوى معاكس قريب جداً من الدخول»).

**R:R.** `rr[i] = |target_i − preferred_entry| / risk`; TP2 < 1.5 R rejects the plan
(«نسبة العائد إلى المخاطرة غير كافية»). Leverage is
never part of the plan or the score.

## 9. Lifecycle

```
developing ─(close)→ confirmed ─(fill)→ active ─→ tp1_hit ─→ tp2_hit ─→ tp3_hit (final)
                          │                  └──→ stopped (final) / closed (time stop, opposite STRONG)
                          ├─(close beyond invalidation before fill)→ invalidated (final)
                          └─(no fill within 6 bars)→ expired (final)
```

- **MARKET** fills at the confirmation close. **ZONE** fills when a later candle trades
  through `preferred_entry`.
- **On the fill candle only the stop is checked**: intrabar order is unknown, so a target on
  that same candle is not credited.
- **Same-candle stop + target**: the **stop is assumed first** (conservative) and the trade is
  flagged `ambiguous`. A gap through the stop exits at the candle open, not at the stop.
- Exits are 1/3 per target. Moving the stop to break-even after TP1 is available but **off**
  (it lowered expectancy in every development variant).
- Time stop: 48 bars after the fill.
- `history` stores every state change. Original fields (plan, score, components) are frozen;
  only lifecycle fields change.

## 10. Persistence, API, WebSocket

Tables (migration `0002_signals`):

- `signals`: frozen original fields plus lifecycle state, evidence JSON and `strategy_version`.
- `signal_outcomes`: exits, gross/net R, ambiguity, MFE/MAE.
- `backtest_runs`: config, data ranges, summary.
- Every row carries `source` (`live`/`backtest`) and `strategy_version`.

REST (authenticated):

| Method | Path                                                 | Returns                                                  |
| ------ | ---------------------------------------------------- | -------------------------------------------------------- |
| GET    | `/api/v1/signals/{symbol}?timeframe=15m`             | `{evaluation, developing, active, last_confirmed}`       |
| GET    | `/api/v1/signals/{symbol}/history?timeframe=&limit=` | persisted signals (≤ 100)                                |
| GET    | `/api/v1/signals/health`                             | strategy version, per-stream active/suppressed, counters |
| GET    | `/api/v1/backtests`, `/api/v1/backtests/{id}`        | stored backtest runs (admin/analyst)                     |

WebSocket events (per subscribed stream, see architecture.md §3):

- `signal.developing` (throttled)
- `signal.confirmed`
- `signal.updated`, which carries one of: a closed-candle evaluation, a lifecycle change, or
  the full state on subscribe
- `signal.closed`

## 11. Frontend

- **`SignalPanel`**: shows
  - الإشارة: class colour from the `--ns-sig-*` tokens
  - قوة الإشارة: `NN/100` and a meter
  - the state line
  - الدخول (range for ZONE), وقف الخسارة, TP1–3, and R:R per target
- A developing hypothesis shows «… — قيد التشكّل» with dashed/amber styling. NEUTRAL shows
  its reason.
- **Details drawer**: setup type, signal strength, state and creation time; component bars
  (points/weight); supporting and opposing factors; MTF context; strategy version.
- **Chart**:
  - markers «شراء 78» / «بيع 81» at confirmation (closed ones faded)
  - developing «شراء؟» markers (faded)
  - Entry / SL / TP1–3 lines for the active signal only (hit targets faded)
  - toggles «علامات الإشارات» / «خطة الصفقة» in the overlay menu
- **Backtest view** `/backtests` (admin/analyst): holdout/dev/all summary, tables by
  symbol, timeframe, setup and regime, and score calibration.
- The risk note «الإشارات تحليلية وليست ضماناً للربح.» is always visible.

## 12. Validation status and research-only timeframes (Phase 4.1)

`app/signal_engine/validation.py` holds the strategy's validation status and its
deployment policy. Neither is ever changed automatically: decisions are documented in
[`research.md`](research.md).

| Status | Arabic | Meaning |
| --- | --- | --- |
| `unproven` | غير مُثبت | no demonstrated edge (the current baseline) |
| `testing` | قيد الاختبار | under historical research |
| `passed_historical` | اجتاز الاختبار التاريخي | met the walk-forward acceptance criteria |
| `forward_test` | اختبار مباشر | live forward test (still analytical, never "trusted") |
| `rejected` | مرفوض | failed; no directional signals |

Allowed transitions: unproven→testing→{passed_historical, rejected};
passed_historical→{forward_test, rejected}; forward_test→rejected; rejected→testing
(re-testing means a new version). Skipping historical validation is impossible (tested).

**Deployment policy.**
- The frozen baseline is `unproven` and labelled «تجريبي». Directional live signals are
  allowed only on its policy timeframes (**15m, 30m, 1h**).
- On **1m, 5m and 10m** the engine still evaluates and shows its reasoning, but a BUY/SELL
  becomes NEUTRAL with «إطار زمني للبحث فقط — لا إشارات اتجاهية لهذا الإطار».
- **LIQUIDITY_REVERSAL and BREAKOUT_CONTINUATION** are EXPERIMENTAL / DISABLED_FOR_SIGNALS.
  They are evaluated and visible in the details drawer, but shown as NEUTRAL with «نوع إعداد
  تجريبي معطّل للإشارات — لم يُظهر أفضلية في البحث». Both were negative in every walk-forward
  window, and breakout was negative even before costs.
- Research candidates (`RESEARCH_CANDIDATES`) are recorded with status `testing` and are never
  emitted live.
- Every `signal.*` event, the REST state and `/signals/health` carry
  `strategy: {version, status, status_ar, label_ar, forward_test, signal_capable, note_ar}`.
- The panel always shows the status badge («تجريبي · غير مُثبت» or «اختبار مباشر»), plus a
  research-only note when relevant.

The policy lives outside `SignalConfig`, so the frozen baseline version is unchanged.

## 13. Known weaknesses

See backtesting.md §8. Most importantly:

- no demonstrated edge after costs;
- an uncalibrated score;
- low-timeframe trades dominated by costs;
- no order-book/funding/derivatives context;
- bar-level simulation (no intrabar path).
