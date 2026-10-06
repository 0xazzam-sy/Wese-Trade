# Wese Trade — Phase 4.2 Prospective Forward Test

> **This is a measurement, not a deployment.** One frozen research candidate is observed on
> **new, unseen** OKX candles and measured honestly. Signals are paper results only:
> «الإشارات قيد الاختبار وليست توصيات مضمونة.» No orders, no exchange accounts, no
> leverage, no auto trading. Nothing is tuned while the test runs.

---

## 1. Why a forward test

Phase 4.1 ([`research.md`](research.md)) found **no robust edge**. The baseline lost
−0.077 R per trade over 2,605 validation trades, and 0 of 64 pre-registered candidates passed.

One exploratory candidate looked positive in the validation windows (+0.322 R, n = 295)
but was **negative before 2026** (−0.068 R, n = 252). That mixed history is exactly why it
must be tested prospectively, on data that did not exist when it was chosen. Historical
re-analysis cannot settle the question.

## 2. Frozen strategy

| Item               | Value                                                                          |
| ------------------ | ------------------------------------------------------------------------------ |
| Research candidate | `wese-trade-research-4.1-c590e82e3a` (loaded, hash-verified, never rebuilt)    |
| Forward version    | **`wese-trade-forward-4.2-a03e20f1d4`**                                        |
| Fingerprint (UI)   | **`4.2-a03e20f`**                                                              |
| Display name       | Wese Trade Forward 4.2                                                         |
| Setup family       | TREND_CONTINUATION only                                                        |
| Signal timeframes  | 15m, 30m, 1h (1m / 5m / 10m are context/research only)                         |
| Threshold          | score ≥ 75, bull/bear spread ≥ 10 (score is **uncalibrated**)                  |
| Regime exclusion   | no signals in `range` or `transitional` regimes                                |
| Entry              | retrace: limit at the confirmation-candle midpoint (never worse than market)   |
| Stop / targets     | structural stop (model A) / structural TP1–TP3 (model A)                       |
| Exit               | runner: 50 % at TP1, 50 % runs to TP3 or stop; max hold 96 bars; no break-even |
| Costs (base)       | taker 0.05 %, maker 0.02 %, slippage 0.02 % per side — fixed at start          |
| STRONG BUY / SELL  | disabled                                                                       |

The forward version is `wese-trade-forward-4.2-` + the first 10 hex characters of a SHA-256
hash. The hash covers the variant definition, signal/tracker config, analysis config,
timeframe policy and context timeframes, universe, cost model, entry/stop/target
descriptions, the decision criteria and the protocol string.

Any change to any of these produces a **different version**. In that case the service
refuses to resume the open run and reports `degraded` (`version_mismatch`). A changed
strategy therefore needs a new run; it can never silently continue an old one.

`GET /api/v1/forward-test/runs/{id}` returns `config_matches_code`, and the UI warns when
the code no longer matches the run.

## 3. Universe

The universe is the 12 Phase 4.1 symbols, chosen **before** any forward data existed and
never re-selected by performance:

`BTCUSDT, ETHUSDT, SOLUSDT, XRPUSDT, DOGEUSDT, HYPEUSDT, NEARUSDT, UNIUSDT, PUMPUSDT,
SUIUSDT, PEPEUSDT, ARBUSDT`

`start` checks each symbol against OKX public instruments (`state == live`). Inactive
symbols are excluded and written into the run notes.

A symbol delisted during the run stops producing signals: `symbol_active` is false in the
gate. Its open signals keep their lifecycle while candles still arrive. The symbol is
listed in `health.unavailable_symbols`.

## 4. Start boundary and restarts (no retroactive signals)

- `started_at` is the UTC wall clock when `start` runs, truncated to whole seconds and
  never backdated.
- A signal can only come from a candle that **opens at or after `started_at`** and is
  **observed closing live**. A candle that was already forming at the start is excluded.
- Seeded history (analyzer warm-up) never creates signals.
- Each (symbol, timeframe) stream stores a **cursor**: the last processed close time.
  - After a restart or a market-data resync, candles after the cursor are _caught up_.
  - Catch-up updates the lifecycle of open signals (fills, TP/SL, expiry) in time order.
  - Catch-up **never creates new signals**: those candles were not observed live.
  - Cursors only move forward, so no candle is processed twice.
- Persisted signal ids are restored into the tracker, so a restart cannot duplicate a
  signal.
- Only **one open run per version** exists. A partial unique index on `strategy_version`
  `WHERE stopped_at IS NULL` enforces this.

## 5. Live evaluation (same engine as research)

`app/forward_test/evaluate.py` uses the canonical pieces:

1. the `MarketAnalyzer` snapshot and the context frames;
2. the shared gate;
3. `research_hypotheses`;
4. `evaluate_hyps`, the same function the Phase 4.1 simulator uses.

A parity test asserts that live output equals research output on the same candles.

The context (higher) timeframes must close at the same instant. Live evaluation waits up
to 15 s for them.

**Feed safety.** A candle is evaluated as `market_stale`, and so produces no signal, when
any of these holds:

- the stream is not `live`;
- OKX health is `disconnected`;
- the evaluation would happen more than 120 s after the candle close.

All signal terms (entry, stop, TP1–3, score, regime, reasons) are **frozen at
confirmation**. Only the lifecycle changes after that.

**Paper fills.**

- A retrace limit fills only if price touches it, and expires if it is never reached.
- When stop and target fall inside the same candle, the stop is assumed first (the
  conservative choice). The trade is flagged `ambiguous`.

## 6. Statuses

| Status                | Arabic                 | Meaning                                                            |
| --------------------- | ---------------------- | ------------------------------------------------------------------ |
| `forward_testing`     | اختبار مباشر           | running; new signals allowed                                       |
| `paused`              | متوقف                  | admin pause: open signals keep their lifecycle; **no new signals** |
| `stopped`             | متوقف                  | admin stop (final); open signals end as `END_OF_DATA`              |
| `passed_forward_test` | اجتاز الاختبار المباشر | every pass criterion met (§8); concluded                           |
| `failed_forward_test` | فشل الاختبار المباشر   | fail criteria met (§8); concluded                                  |

The research strategy status `UNPROVEN` («غير مُثبت») still applies to the Phase 4
baseline. The baseline is now **non-directional**: no baseline BUY/SELL is shown anywhere.

Allowed transitions:

- forward_testing → paused / stopped / passed / failed
- paused → forward_testing / stopped

Every transition is appended to `status_history` with a UTC time and a note. Signals ended
by a stop are reported separately and are **not** counted as closed trades.

## 7. Metrics

The primary metrics are:

- net expectancy (R per closed trade, after costs);
- profit factor;
- max drawdown (R);
- average and median R;
- sample size.

Gross expectancy and gross PF are shown next to the net values. Win rate is secondary.

A _closed trade_ is a final signal that was entered and has a net R. The following are
reported separately and are **not** counted as closed trades:

- expired/unfilled limits;
- signals invalidated before entry;
- signals ended by a run stop.

Breakdowns:

- by timeframe, symbol, regime and side;
- by score bucket (75–79 / 80–84 / 85–89 / 90+);
- the **recent window** (last 30 closed trades).

Average holding time is reported in bars and hours.

A **daily checkpoint** (once per UTC day) snapshots the metrics into
`forward_test_checkpoints`.

## 8. Decision criteria (pre-registered, fixed in the version hash)

**PASS** requires _every_ condition:

- closed trades ≥ **150** (expired/unfilled excluded) **and** elapsed ≥ **30 days**;
- net expectancy > 0;
- profit factor ≥ 1.1;
- max drawdown ≤ max(15 R, 0.2 × trades);
- not dependent on one symbol: expectancy without the best symbol is > 0;
- not dependent on one timeframe: expectancy without the best timeframe is > 0;
- no severe recent deterioration: the last 30 trades have expectancy ≥ −0.10 R.

**FAIL** requires a sufficient sample (≥ 75 closed trades) **and** materially negative
evidence. That means at least two of the following, or one of them once ≥ 150 trades
exist:

- net expectancy ≤ −0.10 R;
- PF ≤ 0.85;
- drawdown > 1.5 × the limit;
- broad deterioration: negative overall, every timeframe negative, and ≥ 75 % of symbols
  negative.

Otherwise the verdict is `INSUFFICIENT_SAMPLE` or `CONTINUE`. The run status changes to
passed/failed automatically at the daily checkpoint.

A PASS means only that the candidate _survived a prospective test_. It is not a guarantee.
No wording such as موثوق / مضمون / عالي الدقة / نسبة نجاح is ever used.

## 9. Persistence

These tables are separate from the research store (`data/research`) and from the baseline
`signals` table:

| Table                      | Purpose                                                                                                                                                                                                       |
| -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `forward_test_runs`        | id, strategy_version, fingerprint, research_version, frozen config, started_at, stopped_at, status, symbols, timeframes, cost_model, minimum_required_trades, minimum_days, notes, status_history, created_at |
| `forward_test_signals`     | frozen terms (inserted once) + lifecycle (forward-only updates); unique (run, signal_id)                                                                                                                      |
| `forward_test_outcomes`    | one row per final signal: gross/net R, fees R, slippage R, holding bars, targets hit, ambiguity                                                                                                               |
| `forward_test_cursors`     | last processed close time per (run, symbol, timeframe)                                                                                                                                                        |
| `forward_test_checkpoints` | one metrics snapshot per run per UTC day                                                                                                                                                                      |

The migration is `0003_forward_test`. DB writes go through one background writer, so a
slow database never blocks the market feed. Write failures show up as `degraded` health.

## 10. API (`/api/v1/forward-test`, authenticated)

| Method | Path                             | Who            | Purpose                                                                        |
| ------ | -------------------------------- | -------------- | ------------------------------------------------------------------------------ |
| GET    | `/status`                        | any user       | dashboard card                                                                 |
| GET    | `/config`                        | admin, analyst | frozen config of the running code                                              |
| GET    | `/health`                        | admin, analyst | running / paused / degraded / stopped, last candle, last evaluation, DB writes |
| GET    | `/runs`, `/runs/{id}`            | admin, analyst | run + metrics + assessment + criteria                                          |
| GET    | `/runs/{id}/signals`             | admin, analyst | history; filters symbol, timeframe, side, state                                |
| GET    | `/runs/{id}/checkpoints`         | admin, analyst | daily snapshots                                                                |
| GET    | `/runs/{id}/export?format=`      | admin, analyst | CSV or JSON (no secrets)                                                       |
| POST   | `/runs/{id}/pause\|resume\|stop` | admin          | the only write actions                                                         |

There is **no** endpoint that edits weights, thresholds, stops, targets, filters, symbols
or timeframes. A test asserts this.

## 11. UI

- The **dashboard card** «استراتيجية الإشارات» shows:
  - the status;
  - the fingerprint;
  - closed trades / 150;
  - net expectancy;
  - the disclaimer.
- The **`/forward-test` page** (admin, analyst; account menu → «الاختبار المباشر») shows:
  - name, version, fingerprint and status;
  - the start time in UTC and local time;
  - symbols, timeframes, health and costs;
  - stat tiles and all breakdowns;
  - the assessment against the criteria;
  - the signal history with filters;
  - CSV/JSON export;
  - admin pause/resume/stop.

  It has no tuning controls.

- The **signal panel** shows:
  - «شراء — اختبار مباشر» / «بيع — اختبار مباشر»;
  - the badge «اختبار مباشر»;
  - the fingerprint;
  - «قوة الإشارة NN/100» with «غير معايرة»;
  - on 1m/5m/10m, «هذا الفريم غير مفعّل للإشارات حالياً».

## 12. Operating the test

```bash
cd backend
python -m app.scripts.forward_test start --notes "..."   # once; never backdated
python -m app.scripts.forward_test status
python -m app.main                                         # the service loads the open run
```

**The backend must keep running for the test to observe candles.**

- While the backend is down, nothing is observed live.
- On restart, the missed candles are caught up for lifecycle only, so a long outage costs
  signals but never fabricates them.
- Outages are visible as a gap in `last_evaluation_at` and in the checkpoints.

**While the test runs, do not:**

- edit `app/forward_test/candidate.py`, the research candidate, signal/analysis configs or
  costs (the version would change and the run would stop resuming);
- lower the threshold because few signals appear (few trades is a valid result);
- delete or edit rows in the `forward_test_*` tables.

## 13. Real run

The real run, its validation and its start time are recorded below.

### Run 1 (the real forward test)

| Field                 | Value                                                           |
| --------------------- | --------------------------------------------------------------- |
| Run id                | 1                                                               |
| Version / fingerprint | `wese-trade-forward-4.2-a03e20f1d4` / `4.2-a03e20f`             |
| `started_at`          | **2026-10-05T07:01:59Z** (wall clock at `start`, not backdated) |
| Symbols               | all 12 active on OKX at start (none excluded)                   |
| Timeframes            | 15m, 30m, 1h                                                    |
| Costs                 | base: taker 0.05 %, maker 0.02 %, slippage 0.02 %               |
| Minimums              | 150 closed trades and 30 days                                   |
| Status                | `forward_testing`                                               |

The first eligible candles were 15m opening 07:15 (closed 07:30), 30m opening 07:30
(closes 08:00) and 1h opening 08:00 (closes 09:00).

At the 07:30 close the service evaluated **exactly 12** candles, all 15m. All 12 were
NEUTRAL (gate reasons: excessive volatility, no clear opportunity, no qualifying setup).
The 07:15 close produced none, as expected.

### Validation (real OKX data, 2026-10-05)

Validation used a **scratch** database with a throwaway run, so that the controls could be
exercised without touching the real run. One check ran on the real run itself (marked
below).

| Check                                             | Result                                                                                                                              |
| ------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| Universe loads                                    | 12/12 symbols live on OKX; 36 streams subscribed (12 × 15m/30m/1h)                                                                  |
| No signals on 1m/5m/10m                           | `/signals/BTCUSDT?timeframe=5m` and `1m`: baseline, `signal_capable=false`, «هذا الفريم غير مفعّل للإشارات حالياً»                  |
| 15m/30m/1h owned by the forward test              | `/signals/…?timeframe=15m` and `1h`: version `…a03e20f1d4`, «اختبار مباشر», `score_calibrated=false`                                |
| Start boundary                                    | started 06:30:06; at the 06:45 close the cursor advanced to 06:45 with **0 evaluations** (the candle opened 06:30:00, before start) |
| Restart (no duplicates)                           | reloaded run 1 with status `forward_testing`; 1 run row; 36 cursors unchanged                                                       |
| Outage across a close                             | server down 06:59:20 → 07:00:45; on restart **36 catch-up candles**, **0 evaluations**, every cursor at 07:00                       |
| Live evaluation after start (on the **real** run) | 07:30 close: 12 × 15m evaluations; the 30m candle opened before start and was not evaluated                                         |
| Pause / resume / stop                             | each recorded in `status_history`; stop sets `stopped_at`; resume after stop → 409 `stopped -> forward_testing is not allowed`      |
| Export                                            | CSV has a metadata line plus a header; JSON has run, metrics, checkpoints and signals; no secrets                                   |
| Persistence errors                                | 0                                                                                                                                   |

### Keeping the test running

The run lives in the backend's database (`backend/data/`, git-ignored), and the service
only observes candles while the backend runs.

- If the host or container is recycled, the run and its rows go with that database.
- In that case, start the backend from a persistent machine with the same database.
- Never create a backdated replacement run.

### Desktop installations (Phase 4.3)

The packaged app keeps its **own permanent** forward test in its app-data database. See
[`desktop.md`](desktop.md) §6.

- On the first launch with no open local run, a **new** run of
  `wese-trade-forward-4.2-a03e20f1d4` starts at the current UTC time. It is never
  backdated.
- Later launches resume that run.

The temporary build-container run above is not migrated and does not become the desktop
run. Container run 1 stopped observing at about 07:36Z, when the container was recycled,
exactly as warned above.

## Chart signal UX (v1.0.0)

* BUY / SELL markers on the chart come ONLY from confirmed forward-test signals of the frozen
  strategy (`wese-trade-forward-4.2-a03e20f1d4`): persisted history from
  `GET /api/v1/forward-test/chart-signals?symbol=&timeframe=` (restored after a restart, never
  re-evaluated) merged with the live WebSocket view, de-duplicated by signal id.
  Structure/liquidity annotations (HH/HL/BOS/CHoCH/OB/FVG…) never create a marker.
* BUY: ▲ below the confirmation candle, «BUY · شراء». SELL: ▼ above it, «SELL · بيع».
  Closed signals keep a muted marker; Entry/SL/TP1-3 lines are drawn for the open signal only.
  No NEUTRAL marker. Hover/click a marker for its details card.
* 15m / 30m / 1h: signals enabled. 1m / 5m / 10m: analysis only, no directional markers.
* Each chart has a status strip («شراء — اختبار مباشر» / «بيع — اختبار مباشر» / «محايد») and
  a «شرح الشارت» legend in Arabic.
* Deterministic UI fixture: `frontend/src/test/fixtures/frozen-signals.json`, generated from the
  real engine replay by `python -m tests.signals.ui_fixtures` (a backend test fails on drift).
  Browser E2E: `scripts/e2e_chart_signals.mjs` (screenshots in `docs/ux/`).
