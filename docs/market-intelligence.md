# Market intelligence engine (Phase 3)

Wese Trade's analysis engine turns normalized OKX candles into **structured,
deterministic market features**: trend, regime, volatility, momentum, volume, swing and
internal structure, liquidity, fair value gaps, order blocks, premium/discount, OTE and
multi-timeframe context.

> **Analysis only.** The engine produces descriptions of the market, never trade
> signals. There is no BUY/SELL/STRONG label, no Entry, Stop-Loss, Take-Profit or
> Risk/Reward, no "final confidence", and no AI/LLM prediction anywhere in Phase 3.
> Any `quality` value is the quality of a detected feature, **not** a probability of
> profit. The Phase 4 signal engine will consume these features.

Every ambiguous trading concept has **one** deterministic definition in this document.
The code (`backend/app/analysis/`) implements exactly these definitions, and its module
docstrings repeat them.

---

## 1. Architecture

```
OKX candles ─► MarketDataEngine ──candle/resync listeners──► AnalysisService (live)
                                                                    │ one MarketAnalyzer per
                                                                    │ (symbol, timeframe)
                                                                    ▼
                                    MarketAnalyzer.update(closed candle)   ◄── the ONE canonical
                                    MarketAnalyzer.snapshot(forming)           implementation
                                                                    │
                    analysis.update (WebSocket)  ◄──────────────────┤
                    GET /api/v1/analysis/{symbol}[/history] ◄───────┘
                    Frontend: panel, MTF panel, chart overlays (display only)
```

```
backend/app/analysis/
  enums.py, models.py, config.py      vocabulary, typed models, ALL tunables
  engine.py                           MarketAnalyzer (orchestrates the trackers)
  series.py                           bounded bar buffer with stable absolute indices
  indicators/  ema, atr, rsi, momentum, volume, candles, stats, state (streaming)
  regime/detector.py                  directional + volatility regime
  structure/   pivots, market_structure (BOS/CHoCH), protected_levels, displacement
  liquidity/   equal_levels, pools, sweeps
  zones/       fvg, order_blocks, premium_discount, ote
  multi_timeframe/context.py          MTF mapping and alignment
  scoring/feature_quality.py          0-100 feature quality (not probability)
  serialize.py                        models -> JSON payloads
  service.py                          live AnalysisService (seeding, cadence, cache)
```

- **One implementation.** `MarketAnalyzer` is a streaming state machine:
  `update(candle)` advances confirmed state by exactly one CLOSED candle. Batch analysis,
  live analysis and (future) backtesting and scanning all run this same loop, so historical
  replay and live results are identical by construction (and tested).
- **The forming candle never mutates state.** `snapshot(forming)` evaluates the forming
  candle read-only and reports what it would imply as `developing` features.
- **Pure and deterministic.** No network or wall-clock access inside the analyzer. The
  only time input is the optional `generated_at` label.
- **Precision.** Analysis uses float64 internally. Analysis values are features, never
  order prices.
- **Frontend.** The browser only displays results. No analysis logic exists in React.

## 2. Indicators

All indicators are streaming (O(1) per candle), seeded deterministically, and computed
from **closed** candles. The forming candle's value is a read-only `peek`.

| Feature | Definition |
|---|---|
| EMA 20/50/100/200 | SMA of the first *n* closes, then `α·close + (1-α)·prev`, `α = 2/(n+1)` |
| EMA slope | `(EMA_t − EMA_{t−5}) / 5` price/bar. **Normalized slope** = slope / ATR (ATR per bar) |
| Distance from price | `(close − EMA) / ATR` |
| EMA spread | `(EMA20 − EMA200) / ATR`. **Expanding** if \|spread\| grew ≥ 0.15 ATR over 5 bars, **compressing** if it shrank ≥ 0.15, else **flat** |
| Stacking | `alignment_score` = number of correctly ordered adjacent pairs (−3…3). **Bullish stack** = EMA20 > 50 > 100 > 200; bearish = reverse; otherwise mixed |
| Trend score | `0.4·(alignment/3) + 0.4·clamp(EMA50 normalized slope / 0.15) + 0.2·clamp(EMA50 distance / 2)`, in −1…1 |
| Trend direction | **bullish** if score ≥ 0.25 **and** EMA50 slope ≥ +0.02 ATR/bar; bearish mirrors this; otherwise neutral. EMA ordering alone is never enough |
| ATR | Wilder ATR(14); also ATR % of price, range/ATR (ATR before the candle) |
| ATR percentile | Percentile rank of ATR% among the previous 100 values (relative to the asset itself, never one fixed threshold) |
| Realized volatility | stdev of 1-bar log returns over 20 bars (%) |
| RSI | Wilder RSI(14), plus slope (3 bars), cross of 50 (`up`/`down`), overbought ≥ 70 and oversold ≤ 30 **as feature flags only** (never "RSI < 30 = buy") |
| Divergence hook | Regular divergence between the last two internal pivots of a side and RSI at those pivots (reported for 10 candles after the confirming pivot) |
| Momentum | ROC(10) %; impulse = the same move in ATR units; acceleration = ROC(5) now − ROC(5) five bars ago |
| Volume | Base-currency volume (OKX `volCcy`); average of the previous 20; relative volume; z-score; percentile among the previous 100; spike ≥ 2× average; contraction ≤ 0.5×. No buy/sell volume is inferred (OKX candles don't provide it) |
| Breakout volume confirmation | A BOS/CHoCH with relative volume ≥ 1.5 (`volume_confirmed`) |
| Candle features | body %, upper/lower wick %, range/ATR, close location (0 = low, 1 = high). Patterns: bullish/bearish engulfing (body engulfs the previous opposite body), bullish/bearish pin (rejection wick ≥ 2× body and ≥ 60% of range), inside bar, strong body (body ≥ 70% of range and range ≥ 1 ATR) |

## 3. Market regime

Direction and volatility are classified on **two separate axes**, so one enum never
carries contradictory states.

**Directional regime.** `er` is the Kaufman efficiency ratio over 20 bars,
`|close_t − close_{t−20}| / Σ|Δclose|`. Rules are evaluated in order:

| Regime | Rule |
|---|---|
| `strong_uptrend` | trend score ≥ 0.6 **and** er ≥ 0.35 **and** swing structure bullish |
| `strong_downtrend` | mirror |
| `uptrend` | trend score ≥ 0.25 and swing structure not bearish |
| `downtrend` | mirror |
| `range` | \|trend score\| < 0.25 and er < 0.3 |
| `transitional` | everything else (e.g. EMAs up but swing structure broke down) |

**Volatility regime.** By ATR percentile: `low` below 20, `normal` from 20 to 80, `high`
from 80 to 95, `extreme` at 95 and above.

**`primary`** is one dominant label. It is the directional regime when a trend exists.
For `range`/`transitional`, a high or extreme volatility gives `high_volatility`, low
volatility gives `low_volatility`, and otherwise the label is `ranging`/`transitional`.
`regime.inputs` exposes every input (shown in the debug view).

## 4. Swing and internal pivots

A **pivot high** at bar *i* with `left = L`, `right = R` satisfies both:
- `high[i] > high` of every bar in `[i−L, i−1]`. The left check is strict, so among
  equal highs the **first** one is the pivot.
- `high[i] ≥ high` of every bar in `[i+1, i+R]`.

Pivot lows mirror this.

| Layer | L / R | Confirmation delay |
|---|---|---|
| Swing (structural) | 5 / 5 | confirmed at the **close of candle i+5** |
| Internal (sensitive) | 2 / 2 | confirmed at the **close of candle i+2** |

Each pivot records `price`, `time` (the pivot candle), `index`, `confirmed_index`,
`confirmed_time` (the close of the confirming candle), `layer` and `status`.

Before confirmation, the most recent candidate (among the last R closed candles plus the
forming candle) is reported in `developing.swing_pivots` / `developing.internal_pivots`
with `status = developing`. Such a candidate can move or vanish.

## 5. No-repaint rules (mandatory)

1. Closed candles are processed strictly in order; anything emitted at candle N uses only
   candles ≤ N.
2. A confirmed pivot, BOS/CHoCH, sweep, FVG or OB is **immutable**. It never moves and
   never disappears, except when it ages out of the retention window (≥ 100 candles; the
   tests enforce this bound).
3. Zones and pools only move **forward** through their lifecycle
   (active → mitigated → invalidated/expired). Their defining fields never change.
   Forward-only annotations: a sweep may later gain a `structure_response`; an equal level
   may later gain touches.
4. Developing features depend on the forming candle and are always labeled
   `developing`. The forming candle never mutates confirmed state.
5. A gap, an out-of-order candle, a corrected closed candle, or an exchange history resync
   makes the live service **re-seed** the analyzer from history. It never patches state.
6. `confirmed_time` is always ≥ the close of the last candle needed to know the fact.

**Seed-window dependence (documented, not repainting).** The live analyzer is seeded from
the latest 1000 candles. A re-seed (e.g. after a restart) starts from a later candle, so
the earliest part of the seed window may classify slightly differently. Results are
deterministic for a given start candle. Backtests fix their start, so they are
reproducible.

## 6. HH / HL / LH / LL

Each confirmed pivot is classified against the previous confirmed pivot **of the same
side and layer**: highs as HH (higher) or LH (lower), lows as HL or LL. `HIGH`/`LOW` mark
the first pivot of a side, or an exact tie. Swing and internal classifications are
independent.

## 7. BOS (Break of Structure)

- **Break levels.** Every confirmed pivot is a candidate break level until a candle
  **closes** beyond it, which consumes it. Wick-only penetration never breaks structure.
- **Neutral** (no structure yet). The first close beyond the most recent unconsumed pivot
  high or low is a BOS and sets the direction.
- **Bullish structure: bullish BOS.**
  - **Swing layer.** A close above the **highest** unconsumed swing high formed after the
    last broken level (the structure high). Closes through lower pivots in between consume
    them silently, so a pull-back's minor highs never create extra events.
  - **Internal layer.** A close above the **most recent** unconsumed internal high.
- **Bearish structure** mirrors this.
- **After a break**, pivots formed at or before the broken level are discarded on that
  side; structure restarts from the break.
- **Event fields.** Each event records: type, direction, broken level (price, index,
  time), break candle (index, time), `confirmed_time` (break-candle close), close,
  displacement (§17), relative volume, `volume_confirmed`, layer. Events are emitted at the
  break candle's close and are immutable.

## 8. CHoCH (Change of Character)

A CHoCH is a close through the **protected level** of the current structure (§9).

- **Bullish structure.** A close below the protected low is a **bearish CHoCH**.
- **Bearish structure.** A close above the protected high is a **bullish CHoCH**.
- **A close below an ordinary higher low is not a CHoCH** on the swing layer.
- **Swing CHoCH** uses the leg-origin protected level, so it is rare and structural.
- **Internal CHoCH** uses a trailing protected level (the latest internal higher low or
  lower high), so it is minor by design and always labeled `internal`.

## 9. Protected highs and lows

When structure breaks **up** at candle *b* through a level formed at bar *p*, the
**protected low** is the lowest low of bars `[p, b]`, i.e. the origin of the breaking
move. A downward break defines the **protected high** in mirror fashion.

- **Swing layer.** The protected level changes only at the next break: the next break in
  the same direction makes it `superseded`, and a CHoCH makes it `broken`.
- **Internal layer.** The protected level additionally **trails**: each newly confirmed,
  unconsumed internal pivot low (in bullish structure) replaces it.

Each level tracks: price, time, layer, status (`active` | `superseded` | `broken`),
`created_time` and `ended_time`.

## 10. Liquidity

- **Tolerance.** `tol = max(0.1 × ATR, 2 × tick size)` (ATR-aware with a tick floor).
- **Equal highs / lows (EQH / EQL).**
  - **Definition.** Two or more confirmed *internal* pivots on the same side whose prices
    differ by at most `tol`, where price never traded beyond the earlier pivot by more
    than `tol` in between.
  - **Level.** The most extreme touch (the highest high, or the lowest low).
  - **Fields.** Touches, first/last touch, tolerance, strength
    (`40 + 20·(touches−2) + 20·tightness`, capped at 100) and status.
  - **Lookback.** A pivot may wait up to 150 candles for its partner.
- **Liquidity pools.**
  - **Sides.** **Buy-side** pools rest above highs (buy stops); **sell-side** pools rest
    below lows (sell stops).
  - **Sources.** Equal highs/lows, and confirmed **swing** pivots.
  - **Merging.** A swing pivot within `tol` of an active pool on the same side adds a
    touch instead of a new pool, and a new equal level absorbs an overlapping swing pool
    (status `merged`).
  - **Lifecycle.** `active` → `swept` | `broken` | `expired` (after 500 candles).
  - **Fields.** Level, side, source, age, touches, and when and how the pool ended.

## 11. Liquidity sweeps

For an **active** buy-side pool at level L, a closed candle with `high > L + tol` is:

- a **liquidity sweep** if it **closes back at or below L**: price traded beyond, was
  rejected, and returned inside;
- a **breakout** (pool `broken`) if it **closes above L**: acceptance beyond the level.
  **A breakout is never a sweep.**

A poke within the tolerance (`L < high ≤ L + tol`) is an equal touch, not a sweep. This is
the same tolerance that defines equal highs. Sell-side pools mirror this.

**Sweep fields:**
- side and level
- wick extreme, and penetration (absolute and in ATR)
- close
- rejection = `(high − close) / range` (buy side)
- quality (0–100): rejection, close distance back inside, moderate depth, pool touches,
  volume
- `structure_response`: the id of an **opposite** structure event (e.g. a bearish internal
  CHoCH after a buy-side sweep) within the next 10 candles

A forming candle that currently satisfies the sweep rule is reported in
`developing.sweeps`.

## 12. Fair value gaps (FVG)

Using closed candles c1, c2, c3:
- **Bullish FVG:** `c3.low > c1.high`, gap `[c1.high, c3.low]`.
- **Bearish FVG:** `c3.high < c1.low`, gap `[c3.high, c1.low]`.

**Known and kept.** The gap is known at c3's close and is anchored to c2 (the displacement
candle). It is kept only if its size is ≥ `max(0.35 × ATR, 2 ticks)` (ATR taken before
c3), so tiny meaningless gaps are never shown.

**Lifecycle (forward-only):**
- `filled`: the deepest share of the gap traded into, wicks included (0–1).
- **mitigated**: filled ≥ 50% (price reached the midpoint, "consequent encroachment").
- **invalidated**: a **close** beyond the far edge (below the bottom of a bullish gap).
  Wicks through do not invalidate.
- **expired**: older than 500 candles.

**Quality** (0–100, zone quality, not probability):
- 25 × size/ATR (capped at 1 ATR)
- 25 × displacement of c2
- 15 × volume expansion
- 15 × alignment with internal structure
- 10 × freshness
- 10 × unfilled share

Invalidated or expired gaps score 0. A gap formed by (last two closed candles + the
forming candle) is reported in `developing.fair_value_gaps`.

## 13. Order blocks (OB)

An OB is created **only** from a confirmed BOS or CHoCH (either layer) **with
displacement**. Not every opposite candle is an order block.

**Bullish OB.** Let the bullish break at candle *b* start from the leg's lowest low,
candle *m*:
- **Block.** Take the **last bearish candle** (close < open) at or before *m*, searching
  back at most 5 candles. Merge it with up to 2 immediately preceding consecutive bearish
  candles.
- **Zone.** `[min(cluster lows, low of m), max(cluster highs)]`.
- **Displacement required.** The strongest candle in `(m, b]` must have displacement ≥ 50.
  If no qualifying candle exists, no OB is created.

**Bearish OB** mirrors this. The same block found by both layers is stored once; a swing
event upgrades its layer to `swing`.

**Lifecycle (forward-only):**
- **Touch.** Price re-enters the zone after being outside it.
- **Mitigated.** The first touch; the block stays valid.
- **Invalidated.** A **close** beyond the far edge by more than
  `max(0.1 × ATR, 2 ticks)` (below the bottom of a bullish OB). Noise within that
  tolerance never invalidates.
- **Expired.** Older than 500 candles.

**Fields.** Each OB records:
- type, high/low/mid, creation time
- source event id and layer
- displacement and strength (`quality`)
- touches, mitigation and invalidation times, age and active status

**Quality** (0–100, not probability):
- 35 × displacement
- 15 × volume
- 15 × layer (swing scores 1, internal 0.5)
- 10 × compactness
- 15 × freshness
- 10 × untouched

Invalidated or expired blocks score 0.

## 14. Premium / discount / equilibrium

The **dealing range** comes from the swing layer, falling back to internal when swing has
no structure:

| Structure | Range |
|---|---|
| bullish | protected low → highest high since it (closed candles) |
| bearish | protected high → lowest low since it |
| neutral | most recent confirmed swing high and swing low |

The range is re-anchored at every structure break, so it is never an arbitrary ancient
range.
- **Equilibrium** = 50%. The band 45–55% is `equilibrium`, above it is `premium`, and
  below it is `discount`.
- `above_range` / `below_range` apply outside the range.
- `position` = price as % of the range, using the live price.

## 15. OTE (Optimal Trade Entry zone)

The OTE uses the same dealing range as its **active impulse**:
- **Bullish structure.** The impulse runs protected low → leg high. OTE =
  `[high − 0.79·span, high − 0.618·span]`, focus at 70.5%.
- **Bearish structure.** Mirror, measured upward from the leg low.

The zone is **active** while the structure keeps its direction (a CHoCH re-anchors or
removes it) and price hasn't passed the impulse origin. `price_in_zone` uses the live
price. Neutral structure has no impulse, so it has no OTE. The thresholds are configurable
(`ote_start`, `ote_focus`, `ote_end`). **An OTE is a zone, never a signal.**

## 16. Multi-timeframe mapping

| Execution | Higher-timeframe context |
|---|---|
| 1m | 5m, 15m |
| 5m | 15m, 1h |
| 10m | 30m, 1h |
| 15m | 30m, 1h |
| 30m | 1h |
| 1h | — (no 4h yet; never fabricated) |

**Confirmed candles only.** Context frames come from analyzers fed with **confirmed**
candles only. The live service subscribes them internally.

**Alignment rule.** The same rule is applied separately to trend direction,
swing-structure direction and directional regime. Up-regimes count as bullish,
down-regimes as bearish, range/transitional as neutral.

| Situation | Alignment |
|---|---|
| no higher timeframe ready | `unavailable` |
| execution neutral | `neutral` |
| every higher timeframe agrees | `strong_bullish` / `strong_bearish` |
| opposite direction is the majority (or all) | `countertrend` |
| higher timeframes contain both directions | `mixed` |
| otherwise (agree or neutral) | `bullish` / `bearish` |

`volatility_aligned` is true when every frame has the same volatility regime.

## 17. Displacement

```
score = 100 × ( 0.3 × body/range              (only if the candle moves in the break direction)
              + 0.3 × min(1, range / ATR / 2)
              + 0.2 × min(1, max(0, relvol − 1) / 1.5)
              + 0.2 × min(1, |close − level| / ATR) )
```

ATR is taken **before** the candle, so a candle is never measured against itself. The
score expresses break strength only; it is not a confidence.

## 18. Developing vs confirmed vs invalidated

| Feature | developing | confirmed | invalidated |
|---|---|---|---|
| Pivot | candidate within the last R candles / forming | at the close of candle i+R | — (never) |
| BOS / CHoCH | forming close beyond the level (`developing.*_breaks`) | at the break-candle close | — (never) |
| Sweep | forming candle satisfies the rule | at the candle close | — |
| FVG | gap involving the forming candle | at c3's close | close beyond the far edge |
| OB | — | at the source break's close | close beyond the far edge ± tolerance |

## 19. Default parameters

All parameters live in `app/analysis/config.py` (`AnalysisConfig`).

| Group | Defaults |
|---|---|
| EMA | 20 / 50 / 100 / 200; slope lookback 5; flat slope < 0.02 ATR/bar |
| ATR | 14; percentile window 100; volatility at 20 / 80 / 95 percentile |
| RSI / momentum | RSI 14, 70/30 flags; ROC 10; acceleration 5 |
| Volume | lookback 20; percentile 100; spike 2×; contraction 0.5×; breakout 1.5× |
| Pivots | swing 5/5; internal 2/2 |
| Liquidity | tolerance max(0.1 ATR, 2 ticks); EQ lookback 150; pool age 500; sweep response 10 |
| FVG | min max(0.35 ATR, 2 ticks); mitigated at 50% fill; age 500 |
| OB | search 5 bars; cluster ≤ 3; min displacement 50; invalidation max(0.1 ATR, 2 ticks); age 500 |
| Premium/discount / OTE | equilibrium band ±5%; OTE 61.8% / 70.5% / 79% |
| Readiness | minimum 300 closed candles (EMA200 + warm-up), else `analysis_ready=false` with a reason; the live service seeds 1000 |

Defaults were sanity-checked for feature density on real data (§21). **They are not
optimized for profit.**

## 20. API, WebSocket, cache and performance

- **`GET /api/v1/analysis/{symbol}?timeframe=`** returns the latest snapshot (served from
  the live analyzer when one exists, otherwise computed on demand from REST history and
  cached for 30 s). It returns `analysis_ready=false` with a `reason`
  (`loading_history`, `insufficient_history`, `history_unavailable`).
- **`GET /api/v1/analysis/{symbol}/history?timeframe=&limit≤300`** returns compact
  per-candle feature rows (trend, regime, RSI, ATR%, relative volume, structure
  directions) plus the confirmed structure events and sweeps in that window.
- **`GET /api/v1/analysis/health`** reports analyzer states and traffic counters.
- **WebSocket `analysis.update`** is sent to the subscribers of a market stream
  `{symbol, timeframe}`; a `market.subscribe` also subscribes analysis.
  - **`kind: "full"`** carries the whole snapshot. It is sent on subscribe, at **every
    candle close** (all structural events confirm at a close), and when
    higher-timeframe context changes.
  - **`kind: "live"`** carries only forming-candle fields: price, forming candle,
    developing features, premium/discount position and OTE. It is sent at most every
    4 s, or within 1 s when a developing structural feature appears or disappears. Raw
    ticks never trigger analysis.
  - **Client side.** The browser applies a live update only on top of the full snapshot
    of the same closed candle; anything else is ignored as stale.
- **Cache.** The latest analyzer and snapshot are kept per `(symbol, timeframe)` in
  memory. Nothing is persisted yet. Snapshots are plain serializable models, so
  persistence for replay can be added later.
- **Performance (measured).**
  - **Cost.** About 0.1 ms per closed candle (seeding 1000 candles takes about 0.1 s) and
    2–3 ms per snapshot.
  - **Payload size.** A full snapshot is about 55 KB; a live update about 1.5 KB.
  - **Incremental.** The live service never re-runs history: one `update` per closed
    candle.

## 21. Feature density (real OKX data, 2026-10-04)

Sample: the last **500 closed candles** of each series, after a 1000-candle warm-up,
fetched live from OKX on 2026-10-04 (a quiet weekend for BTC). Counts are new features
created within the sample; "active" columns are counts at the end of the sample.

| Series | swing pivots | internal pivots | swing BOS | swing CHoCH | int BOS | int CHoCH | EQH | EQL | sweeps | FVG | active FVG | OB | active OB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| BTC 1m | 56 | 100 | 7 | 10 | 24 | 29 | 7 | 1 | 11 | 145 | 19 | 49 | 16 |
| BTC 5m | 61 | 137 | 0 | 0 | 30 | 31 | 6 | 4 | 14 | 83 | 8 | 49 | 15 |
| BTC 15m | 65 | 145 | 2 | 0 | 21 | 29 | 11 | 9 | 28 | 44 | 0 | 39 | 13 |
| BTC 1h | 65 | 140 | 2 | 4 | 24 | 25 | 5 | 8 | 31 | 32 | 5 | 39 | 17 |
| ETH 1m | 57 | 113 | 4 | 1 | 29 | 24 | 8 | 8 | 9 | 151 | 16 | 40 | 9 |
| ETH 5m | 69 | 141 | 5 | 2 | 14 | 35 | 5 | 7 | 20 | 71 | 11 | 44 | 14 |
| ETH 15m | 66 | 148 | 1 | 2 | 22 | 25 | 9 | 6 | 21 | 42 | 3 | 41 | 13 |
| ETH 1h | 64 | 143 | 2 | 1 | 21 | 27 | 10 | 8 | 35 | 26 | 4 | 35 | 14 |
| SOL 1m | 61 | 132 | 4 | 3 | 30 | 26 | 14 | 19 | 14 | 62 | 8 | 47 | 20 |
| SOL 5m | 71 | 137 | 6 | 2 | 24 | 25 | 7 | 9 | 22 | 38 | 3 | 43 | 19 |
| SOL 15m | 62 | 139 | 2 | 3 | 25 | 23 | 9 | 8 | 28 | 36 | 1 | 41 | 14 |
| SOL 1h | 61 | 144 | 6 | 4 | 22 | 25 | 7 | 10 | 24 | 26 | 4 | 43 | 19 |

**Reading:**
- **Swing structure** is deliberately rare (0–17 events per 500 candles). BTC 5m shows 0:
  price stayed inside the swing range for the whole 42-hour sample (83,826–86,804, inside
  the protected low 83,123 and the structure high 87,239), which is correct for swing
  structure.
- **Internal structure** gives about one event per 10 candles.
- **Sweeps, EQH/EQL** are present everywhere without flooding.
- **FVG on 1m** is dense (about 30% of candles) because the weekend 1m candles were tiny
  (BTC median range ≈ $2), so small jumps exceed 0.35 ATR. Most fill within a few candles
  (83% reached 50% fill); active counts stay small. Raising the threshold to 0.5 ATR
  barely changed the count, so it is a data property.
- **Order blocks** come mostly from internal-layer breaks. Most are mitigated or
  invalidated quickly, and the chart shows only the 6 most recent active ones.

**Tuning during Phase 3.** The first draft used the swing rules for the internal layer
too: internal BOS/CHoCH were as rare as swing (pathological). The fix was trailing
internal protected levels and most-recent internal break levels, which gave the ~50
internal events above. FVG minimum size went from 0.25 to 0.35 ATR, and OB minimum
displacement from 40 to 50.

## 22. Real-market validation performed (2026-10-04, ~07:45–08:15 UTC)

All against the **real OKX public API**.

- **`pytest -m live_analysis`.** 12/12 passed (BTC/ETH/SOL × 1m/5m/15m/1h, 1000 real
  candles each). Asserted:
  - no exceptions
  - valid ranges (RSI 0–100, ATR > 0, percentiles, qualities 0–100, zone top > bottom)
  - ordered events and pivots, unique ids, no timestamp after the last closed candle
  - confirmed events 60 candles ago identical now
- **No-lookahead and replay suites.** These run on two committed real OKX fixtures
  (BTC 5m, SOL 1m; §23).
- **Live end-to-end.**
  - Analyzers seeded in about 2 s (999 candles each, including MTF context streams).
  - On 1m, a full snapshot arrived exactly at the candle close (08:10), with about 11 live
    updates in between.
  - No analysis for unselected streams after rapid switching.
  - No console errors.
- **Browser (Chromium, real data).**
  - The panel showed real values for BTC 5m, BTC 15m, ETH 5m and SOL 5m (e.g. BTC 15m:
    trend bullish, "strong uptrend", swing bullish · BOS, buy-side sweep (quality 67),
    ATR 0.08%, RSI 74, relative volume ×2.37, equilibrium 47%; MTF 15m/30m/1h all
    bullish → strong bullish).
  - The 1h chart correctly shows "no higher timeframe yet".
  - Overlay toggles persist locally.
  - No BUY/SELL text anywhere.
- **Visual inspection** (screenshots of BTC 5m, BTC 15m with premium/discount and OTE,
  SOL 5m, ETH 5m; data cross-checked against the snapshot):
  - **BTC 5m.** A bearish CHoCH and BOS before the sell-off, then a bullish CHoCH at about
    06:10, when price closed above the protected high (≈ 84,875) formed in the 21:00
    region. HH/HL/LH labels sit on the visible swing points. Sweep markers sit on wicks
    above prior highs that closed back below. EQL lines sit on clustered lows. The
    protected low sits at the last pull-back low. The large bullish OB is the sell-off
    candle at the leg low before the reversal.
  - **BTC 15m.** The swing dealing range is protected low 83,123 (1 Oct) → leg high
    87,239 (2 Oct); price at 48.5% is equilibrium. The OTE band 83,987–84,695 equals the
    61.8–79% retracement of that impulse exactly.
  - **SOL 5m.** A clean HH/HL staircase with BOS at each close above the prior swing high,
    OBs under the breaking legs, and sweeps at the local tops.
  - **Not claimed.** These are spot checks of the most visible features in recent
    windows, not an exhaustive candle-by-candle audit of every internal pivot.

## 23. Tests

- **Unit tests.** Indicators (EMA, ATR, RSI, momentum, volume, candles), regime, pivots
  (confirmation delay, equal highs, developing pivots), HH/HL/LH/LL, BOS, CHoCH, protected
  levels, wick-not-BOS, displacement, EQH/EQL, pools, sweep vs breakout, tolerance band,
  sweep response, FVG detection/mitigation/invalidation, OB creation/displacement
  requirement/mitigation/tolerance invalidation, premium/discount, OTE, MTF mapping and
  alignment.
- **Snapshot tests.** Snapshot generation, insufficient history, opt-in debug, and a
  recursive check that **no signal or trade-plan field exists** in any payload.
- **No-lookahead suite** (`tests/analysis/test_no_lookahead.py`, real OKX fixtures,
  production config):
  - output at N is identical when everything after N is replaced by a mirrored future
  - confirmed facts never change or vanish within the retention window
  - live incremental == historical replay (whole snapshot payload)
  - no future timestamps
  - developing features never mutate confirmed state

  The suite was **mutation-tested**: injecting a post-confirmation change to a sweep, or
  deleting an old pivot, makes it fail.
- **Service and API tests.** Seeding, incremental advance on close, throttled live
  payloads, gap/correction/resync re-seed, MTF context subscriptions and clean-up, REST
  and WS endpoints, auth, limits.
- **Frontend tests.** Merge/stale logic, panel metrics, overlay model and toggles, the
  panel's loading/unavailable/ready states, MTF panel, no BUY/SELL or Entry/SL/TP values,
  analysis reset on symbol/timeframe switch, replay to a second chart on the same stream,
  and the overlay primitive.

## 24. Known limitations

- **Seed-window dependence.** The live analyzer starts from the latest 1000 candles; the
  earliest part of that window can differ after a re-seed (§5). It is deterministic for a
  fixed start.
- **10m.** Analysis uses aggregated 10m candles, with the same 10m caveats as the market
  data. Its MTF context is 30m/1h.
- **1h** has no higher timeframe until 4h support exists.
- **Displacement on live payloads.** The developing FVG's displacement uses the last
  closed candle's relative volume.
- **Order blocks** are frequent on the internal layer. Quality and the "6 most recent
  active" display limit keep the chart readable; Phase 4 should weight swing OBs higher.
- **Divergence** is a hook only (last two internal pivots), not a validated feature.
- **Full snapshots are about 55 KB** (sent on subscribe and at each close). Live updates
  are small.
- **Persistence.** Nothing is persisted; history and replay persistence is future work.
- **Visual validation** was a spot check of four series (§22), not an exhaustive audit.
