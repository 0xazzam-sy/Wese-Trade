# Execution timing (v1.1): 1m / 5m / 10m under Strategy 4.2

## Why this layer exists

Phases 5–8 tested independent lower-timeframe strategies:
- candle-based families: LTF-5.x, scalp-6 and fast-7;
- MicroScalp, using real trade flow and order book data.

None produced a robust manual-trading edge after costs and entry latency (see the
`docs/research-*.md` files). The final architecture therefore never creates a trade thesis
on 1m / 5m / 10m.

- **Primary signal engine:** the frozen Strategy 4.2 (`wese-trade-forward-4.2-a03e20f1d4`,
  fingerprint `4.2-a03e20f`) on 15m / 30m / 1h. It is unchanged and supplies:
  - direction;
  - the setup;
  - invalidation;
  - the targets.
- **Execution layer:** `backend/app/execution`. It confirms the *entry timing* of an open
  Strategy 4.2 signal on a lower timeframe. A 1m / 5m / 10m BUY / SELL is an execution
  confirmation in the parent direction. It is never an independent or countertrend signal.

## Parent link

| Execution timeframe | Role | Parent timeframes |
| --- | --- | --- |
| 1m | precise entry timing | 15m, 30m |
| 5m | primary execution confirmation | 15m, 30m |
| 10m | bridge between Strategy 4.2 and execution | 30m, 1h |

- **Source of the parent:** the open forward-test signal (`ForwardTestService` trackers).
- **Choosing a parent:** the most recent open parent is used.
- **Conflicting parents:** open parents with opposite sides block execution.
- **What each signal stores:**
  - `parent_strategy`;
  - `parent_strategy_version`;
  - `parent_signal_id`;
  - `parent_symbol`;
  - `parent_timeframe`.

## Decision

Everything below is evaluated on CLOSED candles only, in this hierarchy:

1. **Parent.**
   - None → `NO_SETUP` («لا توجد فرصة تداول مؤكدة حالياً.»).
2. **Location versus the parent plan.** Progress is measured in R from the parent entry.
   - **ideal:** inside the parent zone ± 0.25 execution-ATR.
   - **acceptable:** ≤ 0.35 R beyond the entry.
   - **extended (WAIT):** more than 0.35 R beyond the entry, up to 0.6 R.
   - **missed (`ENTRY_MISSED`):**
     - more than 0.6 R beyond the entry; or
     - R:R to TP1 below 0.8; or
     - the parent has already hit TP1.
   - **invalid (`NO_SETUP`):** beyond the parent invalidation.
3. **Execution evidence.** Each component is scored −1…1 in the parent direction:
   - EMA 20 / 50 / 200 (12);
   - internal BOS / CHoCH (18);
   - support / resistance reaction with level strength (12);
   - liquidity sweep (12);
   - momentum (12);
   - confirmation candle (8);
   - execution-timeframe regime (10);
   - location (10);
   - live microstructure (6).
4. **«قوة توقيت الدخول».** It equals 50 + 50 × weighted sum.
   - Penalties: stale microstructure −15; spread above 3× normal −10.
   - Bands: poor < 40, weak 40–59, acceptable 60–74, strong 75–84, very strong ≥ 85.
   - It describes execution conditions. It is not a win probability.
5. **BUY / SELL confirmation.** All of the following must hold:
   - at least one trigger on this closed candle:
     - EMA20 reclaim;
     - BOS / CHoCH;
     - sweep reclaim;
     - level reaction;
     - momentum recovery;
   - score ≥ 60;
   - location ideal or acceptable;
   - a candle body in the parent direction;
   - R:R to TP1 ≥ 1.0;
   - microstructure not stale.
   - Otherwise the decision is `WAIT`, with the missing evidence listed.

A confirmation needs a candle observed closing live. Seeded history and restart catch-up
never create signals. A display-only evaluation is never shown as BUY / SELL.

## Plan

- **Entry:** the confirmation close. The parent entry is kept for audit, and the UI shows
  only the final entry.
- **Stop:** the parent stop (structural invalidation). It is tightened to the latest
  execution swing ± max(0.25 ATR, 3 ticks) only if both hold:
  - the new stop is tighter than the parent stop;
  - it is at least max(1.5 ATR, 50% of the parent risk) from the entry, so it never sits in
    noise.
- **TP1 / TP2 / TP3:** the parent targets.

## Lifecycle (persisted in `execution_signals`, migration 0004)

- **Starting state:** `READY` (`valid_until` = close + 1 candle; + ½ candle on 10m).
- **Entry:** `ACTIVE` when price trades back to the entry.
- **Targets:** `TP1_HIT` → `TP2_HIT` → `TP3_HIT`.
- **Stop:** `STOPPED`. When the stop and a target fall in the same candle, the stop counts
  first.
- **Missed entry:** `ENTRY_MISSED` when the entry window passes, or price reaches TP1 before
  the entry.
- **Expiry:** `EXPIRED` when the parent ends before entry, or when the holding limit is
  reached (1m: 240, 5m: 144, 10m: 96 candles).
- **One signal per parent:** a parent yields at most one execution signal per stream.
- **Restart:** candles that closed while the app was down advance open signals; they never
  create new ones.

## Live microstructure

`MicroFeed` subscribes OKX public `books5` + `trades`. Subscriptions are reference-counted per
viewed symbol. It provides:
- the spread and its normal level;
- the top-5 book imbalance;
- the 60-second aggressive-flow imbalance.

Health states:
- **ok.**
- **degraded:** the book is more than 5 s old, or the spread is above 3× normal.
- **stale:** the book is more than 15 s old, or the socket is down. No new confirmation is
  made while stale.
- **unavailable:** falls back to candle / structure logic.

OI and liquidation features are not used, because no usable history exists. The research
collector (`app.research.micro.collector`) keeps gathering them.

## Interfaces

- **WebSocket:** `execution.update` per subscribed 1m / 5m / 10m stream. It carries:
  - the evaluation;
  - the signal;
  - markers;
  - the EMA / level overlay;
  - micro health.
- **REST:**
  - `GET /api/v1/execution/{symbol}?timeframe=`;
  - `GET /api/v1/execution/{symbol}/history`;
  - `GET /api/v1/execution/health`.
- **No order endpoints.** Execution is manual.
