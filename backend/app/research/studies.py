"""Phase 4.1 research studies over pass-1 data (see docs/research.md for the protocol).

Every study is computed on REAL OKX data from the research store. Variants are run with
the canonical SignalTracker (`simulate.run`); score research uses isolated hypothesis
outcomes. Design decisions (score weights, filters) are derived ONLY from the
pre-period (before W1); W1-W3 are validation windows reported separately.
"""

from __future__ import annotations

import math
import multiprocessing as mp
from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from statistics import mean, median
from typing import Any

from app.backtesting.metrics import compute
from app.market_data.timeframes import Timeframe
from app.research.collect import ALL_FAMILIES, SeriesResearch
from app.research.ltf import ltf_entries
from app.research.simulate import (
    BASELINE,
    COSTS,
    FILTERS,
    Outcome,
    ScoreModel,
    Variant,
    isolated_outcomes,
    run,
)
from app.research.walkforward import (
    MIN_GROUP_TRADES,
    Window,
    assess,
    grouped,
    per_window,
    stats,
    validation_trades,
    window_of,
)
from app.signal_engine.config import DEFAULT_SIGNAL_CONFIG
from app.signal_engine.models import Signal, TradePlan

SeriesMap = dict[tuple[str, str], SeriesResearch]
_SERIES: SeriesMap = {}
COST_FLOOR_REASON = "وقف الخسارة المنطقي أصغر من تكلفة التداول والضوضاء"
SIGNAL_TFS = ("5m", "15m", "30m", "1h")
FAMILY_SHORT = {
    "TREND_CONTINUATION": "trend",
    "PULLBACK_CONTINUATION": "pullback",
    "BREAKOUT_CONTINUATION": "breakout",
    "LIQUIDITY_REVERSAL": "reversal",
}


# --- running variants in parallel ---------------------------------------------------------------
def _run_one(args: tuple[Variant, tuple[str, str]]) -> tuple[str, list[Signal]]:
    v, key = args
    return v.name, run(v, _SERIES[key])


def run_variants(
    series: SeriesMap,
    variants: Sequence[Variant],
    *,
    timeframes: Iterable[str] | None = None,
    workers: int = 4,
) -> dict[str, list[Signal]]:
    """{variant name: trades over the selected series}. Fork workers share `series`."""
    global _SERIES
    _SERIES = series
    tfs = set(timeframes) if timeframes is not None else None
    keys = [k for k in series if tfs is None or k[1] in tfs]
    tasks = [(v, k) for v in variants for k in keys]
    out: dict[str, list[Signal]] = {v.name: [] for v in variants}
    ctx = mp.get_context("fork")
    with ctx.Pool(workers) as pool:
        for name, trades in pool.imap_unordered(_run_one, tasks, chunksize=4):
            out[name].extend(trades)
    for trades in out.values():
        trades.sort(key=lambda s: (s.confirmed_time, s.symbol, s.timeframe))
    return out


# --- summaries --------------------------------------------------------------------------------
def family_of(s: Signal) -> str:
    return s.family.value


def summarize(
    trades: Sequence[Signal],
    windows: Sequence[Window],
    fresh: frozenset[str],
    *,
    detail: bool = True,
) -> dict[str, Any]:
    val = validation_trades(trades, windows)
    out: dict[str, Any] = {
        "all_periods": stats(trades),
        "validation": stats(val),
        "windows": per_window(trades, windows),
        "pre_period": stats([s for s in trades if window_of(s.confirmed_time, windows) == "pre"]),
        "fresh_validation": stats([s for s in val if s.symbol in fresh]),
        "anchor_validation": stats([s for s in val if s.symbol not in fresh]),
        "assessment": _assessment(trades, windows, fresh),
    }
    if detail:
        out["by_timeframe"] = grouped(val, lambda s: s.timeframe)
        out["by_symbol"] = grouped(val, lambda s: s.symbol)
        out["by_family"] = grouped(val, family_of)
        out["by_regime"] = grouped(val, lambda s: s.regime or "unknown")
        out["by_side"] = grouped(val, lambda s: s.side.value)
        out["by_window_timeframe"] = {
            w.name: grouped([s for s in val if w.contains(s.confirmed_time)], lambda s: s.timeframe)
            for w in windows
        }
    return out


def _assessment(
    trades: Sequence[Signal], windows: Sequence[Window], fresh: frozenset[str]
) -> dict[str, Any]:
    a = assess(trades, windows, fresh_symbols=fresh)
    return {"status": a.status, "reasons": list(a.reasons)}


def brief(summary: dict[str, Any]) -> dict[str, Any]:
    v = summary["validation"]
    return {
        "val_n": v["entered"],
        "val_exp": v["expectancy"],
        "val_pf": v["profit_factor"],
        "val_dd": v["max_drawdown_r"],
        "val_gross": v["gross_expectancy"],
        "windows": {
            k: (w["entered"], w["expectancy"], w["profit_factor"])
            for k, w in summary["windows"].items()
        },
        "fresh": (
            summary["fresh_validation"]["entered"],
            summary["fresh_validation"]["expectancy"],
        ),
        "pre": (summary["pre_period"]["entered"], summary["pre_period"]["expectancy"]),
        "assessment": summary["assessment"],
    }


# --- cost efficiency per timeframe ------------------------------------------------------------
def cost_efficiency(series: SeriesMap, outcomes: Sequence[Outcome]) -> dict[str, Any]:
    rt = DEFAULT_SIGNAL_CONFIG.round_trip_cost_rate() * 100  # % of price, market both sides
    out: dict[str, Any] = {"round_trip_cost_pct": rt}
    by_tf: dict[str, dict[str, Any]] = {}
    for tf in sorted({k[1] for k in series}, key=lambda t: Timeframe(t).seconds):
        hyps = [
            h for (sym, t), s in series.items() if t == tf for tr in s.triggers for h in tr.hyps
        ]
        atr_pcts = [h.features["atr_pct"] for h in hyps if h.features.get("atr_pct")]
        plans = [h.plans["base/A/A"] for h in hyps]
        floor_rejects = sum(1 for p in plans if p == COST_FLOOR_REASON)
        valid = [p for p in plans if isinstance(p, TradePlan)]
        risk_pct = [p.risk / p.preferred_entry * 100 for p in valid if p.preferred_entry]
        oc = [o for o in outcomes if o.timeframe == tf and o.entered and o.cost_r is not None]
        costs = [o.cost_r for o in oc if o.cost_r is not None]
        med_atr = median(atr_pcts) if atr_pcts else None
        by_tf[tf] = {
            "hypotheses": len(hyps),
            "median_atr_pct": med_atr,
            "cost_r_if_stop_1atr": (rt / med_atr) if med_atr else None,
            "cost_r_if_stop_0_5atr": (rt / (0.5 * med_atr)) if med_atr else None,
            "plans_rejected_cost_floor_pct": 100 * floor_rejects / len(plans) if plans else None,
            "median_plan_risk_pct": median(risk_pct) if risk_pct else None,
            "median_realized_cost_r": median(costs) if costs else None,
            "mean_realized_cost_r": mean(costs) if costs else None,
            "isolated_trades": len(oc),
        }
        rejected = by_tf[tf]["plans_rejected_cost_floor_pct"] or 0.0
        realized = by_tf[tf]["median_realized_cost_r"]
        # Structurally unsuitable: most structural stops are smaller than the cost floor
        # (the plan cannot exist), or friction eats >= 0.25R per trade when it does.
        by_tf[tf]["verdict"] = (
            "STRUCTURALLY_UNSUITABLE"
            if rejected >= 50 or (realized is not None and realized >= 0.25)
            else "COST_HEAVY"
            if realized is not None and realized >= 0.15
            else "OK"
        )
    out["by_timeframe"] = by_tf
    return out


# --- score research -------------------------------------------------------------------------------
def _rank(xs: Sequence[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        r = (i + j) / 2
        for k in range(i, j + 1):
            ranks[order[k]] = r
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 10:
        return None
    rx, ry = _rank(xs), _rank(ys)
    mx, my = mean(rx), mean(ry)
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in rx) * sum((b - my) ** 2 for b in ry))
    return num / den if den else None


def pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 10:
        return None
    mx, my = mean(xs), mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys, strict=True))
    den = math.sqrt(sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys))
    return num / den if den else None


def _exp(rs: Sequence[float]) -> float | None:
    return round(mean(rs), 4) if rs else None


def quantiles(rows: Sequence[tuple[float, float]], q: int = 5) -> list[dict[str, Any]]:
    """Expectancy by value quantile (rows = (value, net R)), grouped by value ranges."""
    if not rows:
        return []
    srt = sorted(rows)
    out = []
    for k in range(q):
        part = srt[k * len(srt) // q : (k + 1) * len(srt) // q]
        if part:
            rs = [r for _, r in part]
            out.append(
                {"q": k + 1, "lo": part[0][0], "hi": part[-1][0], "n": len(part), "exp": _exp(rs)}
            )
    return out


COMPONENTS = (
    "htf",
    "structure",
    "liquidity",
    "location",
    "trend",
    "displacement",
    "volume",
    "candle",
    "momentum",
)


def component_analysis(
    outcomes: Sequence[Outcome], windows: Sequence[Window], fresh: frozenset[str]
) -> dict[str, Any]:
    entered = [o for o in outcomes if o.entered and o.net_r is not None]
    out: dict[str, Any] = {}
    for name in COMPONENTS:

        def rows(subset: Iterable[Outcome], name: str = name) -> list[tuple[float, float]]:
            return [(o.components[name], o.net_r) for o in subset if name in o.components]  # type: ignore[misc]

        pre = [o for o in entered if window_of(o.time, windows) == "pre"]
        r_pre = rows(pre)
        info: dict[str, Any] = {
            "n_pre": len(r_pre),
            "spearman_pre": spearman([a for a, _ in r_pre], [b for _, b in r_pre]),
            "quintiles_pre": quantiles(r_pre),
        }
        info["significance_2se"] = 2 / math.sqrt(len(r_pre)) if r_pre else None
        stability: dict[str, Any] = {}
        for w in windows:
            r = rows(o for o in entered if w.contains(o.time))
            stability[w.name] = spearman([a for a, _ in r], [b for _, b in r])
        for tf in SIGNAL_TFS:
            r = rows(o for o in pre if o.timeframe == tf)
            stability[f"pre_{tf}"] = spearman([a for a, _ in r], [b for _, b in r])
        for label, sel in (("pre_anchor", False), ("pre_fresh", True)):
            r = rows(o for o in pre if (o.symbol in fresh) == sel)
            stability[label] = spearman([a for a, _ in r], [b for _, b in r])
        info["stability"] = stability
        out[name] = info
    # penalties: expectancy with vs without each penalty code (pre-period)
    pre = [o for o in entered if window_of(o.time, windows) == "pre"]
    pens: dict[str, Any] = {}
    codes = sorted({c for o in pre for c in o.penalties})
    for code in codes:
        with_p = [o.net_r for o in pre if code in o.penalties and o.net_r is not None]
        without = [o.net_r for o in pre if code not in o.penalties and o.net_r is not None]
        pens[code] = {"n_with": len(with_p), "exp_with": _exp(with_p), "exp_without": _exp(without)}
    out["_penalties_pre"] = pens
    # overall score (baseline) vs outcome
    r = [(o.score, o.net_r) for o in pre if o.net_r is not None]
    out["_baseline_score_pre"] = {
        "spearman": spearman([a for a, _ in r], [b for _, b in r]),
        "quintiles": quantiles(r),
    }
    return out


def correlation_matrix(outcomes: Sequence[Outcome], windows: Sequence[Window]) -> dict[str, Any]:
    """Pearson correlations among trend-like information (double-counting review)."""
    pre = [o for o in outcomes if window_of(o.time, windows) == "pre"]
    regime_aligned = {
        "long": {
            "uptrend": 1.0,
            "strong_uptrend": 1.0,
            "downtrend": -1.0,
            "strong_downtrend": -1.0,
        },
        "short": {
            "downtrend": 1.0,
            "strong_downtrend": 1.0,
            "uptrend": -1.0,
            "strong_uptrend": -1.0,
        },
    }
    cols: dict[str, Callable[[Outcome], float | None]] = {
        "htf": lambda o: o.components.get("htf"),
        "structure": lambda o: o.components.get("structure"),
        "trend": lambda o: o.components.get("trend"),
        "regime_aligned": lambda o: regime_aligned[o.side].get(o.features.get("regime") or "", 0.0),
        "swing_aligned": lambda o: float(o.features.get("swing") or 0),
        "htf1_trend": lambda o: o.features.get("htf1_trend"),
        "momentum": lambda o: o.components.get("momentum"),
    }
    out: dict[str, dict[str, float | None]] = {}
    names = list(cols)
    for a in names:
        out[a] = {}
        for b in names:
            pairs = [(cols[a](o), cols[b](o)) for o in pre]
            pairs = [(x, y) for x, y in pairs if x is not None and y is not None]
            out[a][b] = None if not pairs else pearson([x for x, _ in pairs], [y for _, y in pairs])  # type: ignore[misc]
    return out


def derive_score_model(analysis: dict[str, Any]) -> ScoreModel:
    """Weights from PRE-PERIOD information only: keep components whose Spearman rho with
    net R is positive beyond 2 standard errors AND positive in both the anchor and fresh
    pre-period subsets; weight proportional to rho. Penalties are kept only if penalized
    hypotheses did worse in the pre-period."""
    weights: list[tuple[str, float]] = []
    for name in COMPONENTS:
        info = analysis[name]
        rho, se = info["spearman_pre"], info["significance_2se"]
        st = info["stability"]
        if rho is None or se is None:
            continue
        if rho > se and (st.get("pre_anchor") or 0) > 0 and (st.get("pre_fresh") or 0) > 0:
            weights.append((name, round(100 * rho, 2)))
    codes = tuple(
        code
        for code, p in analysis["_penalties_pre"].items()
        if p["exp_with"] is not None
        and p["exp_without"] is not None
        and p["exp_with"] < p["exp_without"]
        and p["n_with"] >= 30
    )
    if not weights:
        return ScoreModel("s41_none", weights=(("structure", 1.0),), penalty_scale=0.0)
    return ScoreModel("s41", weights=tuple(weights), penalty_codes=codes)


def calibration(trades: Sequence[Signal], windows: Sequence[Window]) -> list[dict[str, Any]]:
    val = validation_trades(trades, windows)
    edges = [(60, 65), (65, 70), (70, 75), (75, 80), (80, 85), (85, 90), (90, 101)]
    out = []
    for lo, hi in edges:
        part = [s for s in val if lo <= s.score < hi]
        st = compute(part)
        out.append(
            {
                "bucket": f"{lo}-{hi - 1}" if hi <= 100 else f"{lo}+",
                "n": st.entered,
                "exp": st.expectancy,
                "pf": st.profit_factor,
                "win": st.win_rate,
                "avg_r": st.avg_r,
                "sample": "OK" if st.entered >= MIN_GROUP_TRADES else "INSUFFICIENT_SAMPLE",
            }
        )
    return out


# --- interactions --------------------------------------------------------------------------
INTERACTIONS: dict[str, tuple[Callable[[Outcome], bool], Callable[[Outcome], bool]]] = {
    "htf_aligned x swing_aligned": (
        lambda o: o.features.get("htf1_trend") == 1,
        lambda o: o.features.get("swing") == 1,
    ),
    "sweep x internal_choch": (
        lambda o: bool(o.features.get("sweep_recent")),
        lambda o: o.features.get("trigger") == "internal:CHOCH",
    ),
    "order_block x discount": (
        lambda o: bool(o.features.get("ob_support")),
        lambda o: (o.features.get("pd_pos") or 100) <= 50,
    ),
    "displacement x relvol (swing BOS)": (
        lambda o: (
            (o.features.get("displacement") or 0) >= 50 and o.features.get("trigger") == "swing:BOS"
        ),
        lambda o: (o.features.get("relvol") or 0) >= 1.2,
    ),
}


def interactions(outcomes: Sequence[Outcome], windows: Sequence[Window]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    entered = [o for o in outcomes if o.entered and o.net_r is not None]
    for name, (fa, fb) in INTERACTIONS.items():
        cells: dict[str, Any] = {}
        for period in ("pre", "validation"):
            sub = [o for o in entered if (window_of(o.time, windows) == "pre") == (period == "pre")]
            for a in (True, False):
                for b in (True, False):
                    rs = [o.net_r for o in sub if fa(o) == a and fb(o) == b and o.net_r is not None]
                    cells[f"{period}:{'A' if a else 'notA'}&{'B' if b else 'notB'}"] = {
                        "n": len(rs),
                        "exp": _exp(rs),
                    }
        out[name] = cells
    return out


# --- funding -----------------------------------------------------------------------------------
def funding_study(
    outcomes: Sequence[Outcome],
    funding: dict[str, list[tuple[int, float]]],
    windows: Sequence[Window],
) -> dict[str, Any]:
    """Funding known at signal time (latest settled rate <= confirmation). No lookahead."""
    from bisect import bisect_right

    rows = []
    start = min((v[0][0] for v in funding.values() if v), default=None)
    for o in outcomes:
        series = funding.get(o.symbol)
        if not series or not o.entered or o.net_r is None:
            continue
        times = [ms // 1000 for ms, _ in series]
        i = bisect_right(times, o.time) - 1
        if i < 0:
            continue
        rate = series[i][1]
        crowded = (rate >= 0.0003 and o.side == "long") or (rate <= -0.0003 and o.side == "short")
        against = (rate <= -0.0003 and o.side == "long") or (rate >= 0.0003 and o.side == "short")
        rows.append((crowded, against, o.net_r, window_of(o.time, windows)))

    def cell(f: Callable[[tuple[bool, bool, float, str]], bool]) -> dict[str, Any]:
        rs = [r[2] for r in rows if f(r)]
        return {"n": len(rs), "exp": _exp(rs)}

    return {
        "coverage_start_ms": start,
        "rows": len(rows),
        "crowded_side": cell(lambda r: r[0]),
        "contrarian_side": cell(lambda r: r[1]),
        "neutral_funding": cell(lambda r: not r[0] and not r[1]),
        "windows_covered": sorted({r[3] for r in rows}),
        "open_interest": "OKX public OI history: 1H granularity only ~30 days, 5m ~2 days, "
        "1D ~180 days -> insufficient for walk-forward; not studied as a signal input",
    }


# --- reversal diagnostics -----------------------------------------------------------------------
def reversal_diagnostics(outcomes: Sequence[Outcome]) -> dict[str, Any]:
    rev = [
        o
        for o in outcomes
        if o.family == "LIQUIDITY_REVERSAL" and o.entered and o.net_r is not None
    ]

    def by(f: Callable[[Outcome], str]) -> dict[str, Any]:
        groups: dict[str, list[float]] = defaultdict(list)
        for o in rev:
            groups[f(o)].append(o.net_r)  # type: ignore[arg-type]
        return {k: {"n": len(v), "exp": _exp(v)} for k, v in sorted(groups.items())}

    return {
        "n": len(rev),
        "net_exp": _exp([o.net_r for o in rev]),  # type: ignore[misc]
        "gross_exp": _exp([o.gross_r for o in rev if o.gross_r is not None]),
        "by_htf1_trend": by(lambda o: str(o.features.get("htf1_trend"))),
        "by_regime": by(lambda o: str(o.features.get("regime"))),
        "by_sweep_quality": by(
            lambda o: (
                "liquidity>=0.75" if o.components.get("liquidity", 0) >= 0.75 else "liquidity<0.75"
            )
        ),
        "by_risk_atr": by(
            lambda o: "<1ATR" if o.risk_atr < 1 else "1-2ATR" if o.risk_atr < 2 else ">=2ATR"
        ),
        "by_trigger": by(lambda o: str(o.features.get("trigger"))),
        "by_timeframe": by(lambda o: o.timeframe),
    }


# --- LTF execution -------------------------------------------------------------------------------
def ltf_study(
    series: SeriesMap, trades: Sequence[Signal], windows: Sequence[Window]
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    cfg = DEFAULT_SIGNAL_CONFIG
    for htf in ("15m", "30m"):
        a_all: list[Signal] = []
        d_all: list[Signal] = []
        counts: dict[str, int] = defaultdict(int)
        native = [s for s in trades if s.timeframe == htf]
        for sym in sorted({s.symbol for s in native}):
            ltf = series.get((sym, "5m"))
            if ltf is None:
                continue
            sigs = [s for s in native if s.symbol == sym]
            a5, d5, c = ltf_entries(sigs, ltf, Timeframe(htf), cfg)
            a_all += a5
            d_all += d5
            for k, v in c.items():
                counts[k] += v
        out[htf] = {
            "counts": dict(counts),
            "native_htf_bars": stats(validation_trades([s for s in native], windows)),
            "A5_market_at_confirmation": stats(validation_trades(a_all, windows)),
            "D5_5m_choch_entry": stats(validation_trades(d_all, windows)),
            "A5_windows": per_window(a_all, windows),
            "D5_windows": per_window(d_all, windows),
        }
    return out


def isolated_all(series: SeriesMap, plan_key: str = "base/A/A") -> list[Outcome]:
    out: list[Outcome] = []
    for s in series.values():
        out += isolated_outcomes(s, plan_key=plan_key)
    return out


def variants_with(base: Variant, **changes: Any) -> Variant:
    return replace(base, **changes)


__all__ = [
    "ALL_FAMILIES",
    "BASELINE",
    "COSTS",
    "FAMILY_SHORT",
    "FILTERS",
    "calibration",
    "component_analysis",
    "compute",
    "correlation_matrix",
    "cost_efficiency",
    "derive_score_model",
    "funding_study",
    "interactions",
    "isolated_all",
    "ltf_study",
    "reversal_diagnostics",
    "run_variants",
    "stats",
    "summarize",
]
