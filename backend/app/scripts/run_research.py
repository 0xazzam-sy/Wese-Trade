"""Phase 4.1 signal-edge research on REAL OKX data (research store).

    python -m app.scripts.research_fetch --select && python -m app.scripts.research_fetch
    python -m app.scripts.run_research --name phase41

Pass 1 (cached per series) records every hypothesis; the studies then run research
variants through the canonical SignalTracker with chronological walk-forward windows.
Writes data/research/reports/<name>.json and a `research_runs` row in the research store.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import asdict, replace
from typing import Any

from app.analysis.config import DEFAULT_CONFIG as ANALYSIS_CONFIG
from app.analysis.multi_timeframe.context import context_timeframes
from app.market_data.timeframes import Timeframe
from app.research import studies as st
from app.research import universe
from app.research.pass1 import run_pass1
from app.research.simulate import BASELINE, BASELINE_SCORE, COSTS, Variant
from app.research.store import RESEARCH_DIR, ResearchStore
from app.research.walkforward import (
    MIN_GROUP_TRADES,
    MIN_VALIDATION_TRADES,
    MIN_WINDOW_TRADES,
    development,
    make_windows,
    validation,
)

REPORT_DIR = RESEARCH_DIR / "reports"
TREND = ("TREND_CONTINUATION",)
TREND_PULLBACK = ("TREND_CONTINUATION", "PULLBACK_CONTINUATION")
NO_REVERSAL = ("TREND_CONTINUATION", "PULLBACK_CONTINUATION", "BREAKOUT_CONTINUATION")
WEAK_REGIMES = ("range", "transitional")
SCOPES = {
    "5m": ("5m",),
    "15m": ("15m",),
    "30m": ("30m",),
    "1h": ("1h",),
    "15m-1h": ("15m", "30m", "1h"),
}


def analysis_version() -> str:
    raw = json.dumps(asdict(ANALYSIS_CONFIG), sort_keys=True, default=str)
    return f"analysis-{hashlib.sha256(raw.encode()).hexdigest()[:10]}"


def log(*parts: Any) -> None:
    print(time.strftime("%H:%M:%S"), *parts, flush=True)


def candidate_grid(s41: Any) -> list[Variant]:
    out = []
    for fam_name, fams in (
        ("trend", TREND),
        ("trend+pullback", TREND_PULLBACK),
        ("no-reversal", NO_REVERSAL),
        ("all", st.ALL_FAMILIES),
    ):
        for score in (BASELINE_SCORE, s41):
            for thr in (65.0, 70.0, 75.0, 80.0):
                for regimes in ((), WEAK_REGIMES):
                    scope = "no-weak-regime" if regimes else "all-regimes"
                    name = f"cand:{fam_name}|{score.name}|t{int(thr)}|{scope}"
                    out.append(
                        Variant(
                            name,
                            families=fams,
                            score=score,
                            threshold=thr,
                            excluded_regimes=regimes,
                        )
                    )
    return out


def walk_forward_selection(
    results: dict[str, list[Any]],
    grid: list[Variant],
    windows: list[Any],
    scope: tuple[str, ...],
    fresh: frozenset[str],
) -> dict[str, Any]:
    """For each validation window: choose the candidate with the best DEVELOPMENT expectancy
    (data strictly before the window, >= 100 trades), then record its validation result."""
    chosen = []
    picked_trades = []
    for w in windows:
        best = None
        for v in grid:
            trades = [s for s in results[v.name] if s.timeframe in scope]
            dev = st.compute(development(trades, w))
            if dev.entered < 100 or dev.expectancy is None:
                continue
            key = (dev.expectancy, dev.profit_factor or 0)
            if best is None or key > best[0]:
                best = (key, v, dev)
        if best is None:
            chosen.append(
                {
                    "window": w.name,
                    "chosen": None,
                    "reason": "no candidate with >= 100 development trades",
                }
            )
            continue
        _, v, dev = best
        trades = [s for s in results[v.name] if s.timeframe in scope]
        val = validation(trades, w)
        picked_trades += val
        vs = st.stats(val)
        chosen.append(
            {
                "window": w.name,
                "chosen": v.name,
                "version": v.version,
                "dev_n": dev.entered,
                "dev_exp": dev.expectancy,
                "dev_pf": dev.profit_factor,
                "val_n": vs["entered"],
                "val_exp": vs["expectancy"],
                "val_pf": vs["profit_factor"],
                "val_sample": vs["sample"],
            }
        )
    agg = st.stats(picked_trades)
    return {
        "per_window": chosen,
        "out_of_sample_selected": agg,
        "fresh_only": st.stats([s for s in picked_trades if s.symbol in fresh]),
    }


def main(
    name: str,
    workers: int,
    skip_pass1: bool,
    symbols: list[str] | None,
    timeframes: list[str] | None,
) -> None:
    started = time.time()
    members = [m for m in universe.load() if not symbols or m.symbol in symbols]
    fresh = frozenset(m.symbol for m in members if not m.anchor)
    jobs: list[tuple[str, str, float, int | None]] = []
    for m in members:
        tfs = ["5m", "15m", "30m", "1h"] + (["1m", "10m"] if m.anchor else [])
        tfs = [tf for tf in tfs if not timeframes or tf in timeframes]
        jobs += [(m.symbol, tf, m.tick_size, None) for tf in tfs]
    if not skip_pass1:
        log("pass 1:", len(jobs), "series")
        for line in run_pass1(jobs, workers=workers):
            log("  ", line)
    keys = [(sym, tf) for sym, tf, _, _ in jobs]

    store = ResearchStore()
    coverage = {
        f"{s}:{tf}": asdict(store.coverage(s, Timeframe(tf) if tf != "10m" else Timeframe.M5))
        for s, tf, _, _ in jobs
    }
    funding = {m.symbol: store.load_funding(m.symbol) for m in members}
    end = min(
        (c["last_ms"] + Timeframe(k.split(":")[1]).milliseconds) // 1000
        for k, c in coverage.items()
        if k.split(":")[1] in st.SIGNAL_TFS and c["last_ms"] is not None
    )
    windows = make_windows(end, count=3, block_days=91)
    log(
        "windows",
        [
            (
                w.name,
                time.strftime("%Y-%m-%d", time.gmtime(w.start)),
                time.strftime("%Y-%m-%d", time.gmtime(w.end)),
            )
            for w in windows
        ],
    )
    report: dict[str, Any] = {
        "name": name,
        "baseline_version": BASELINE.version,
        "analysis_version": analysis_version(),
        "windows": [asdict(w) for w in windows],
        "symbols": [asdict(m) for m in members],
        "fresh_symbols": sorted(fresh),
        "coverage": coverage,
        "costs": {k: asdict(v) for k, v in COSTS.items()},
        "mtf_roles": {
            tf: [c.value for c in context_timeframes(Timeframe(tf))]
            for tf in ("1m", "5m", "10m", "15m", "30m", "1h")
        },
        "sample_rules": {
            "min_group": MIN_GROUP_TRADES,
            "min_window": MIN_WINDOW_TRADES,
            "min_validation": MIN_VALIDATION_TRADES,
        },
    }

    # --- isolated hypothesis outcomes (score research, cost efficiency, diagnostics) ---
    outcomes = []
    raw_costs = {}
    for key, oc, raw in st.parallel(st.series_phase_a, keys, workers):
        outcomes += oc
        raw_costs[key] = raw
    log("isolated outcomes", len(outcomes))
    signal_outcomes = [o for o in outcomes if o.timeframe in st.SIGNAL_TFS]
    report["cost_efficiency"] = st.cost_efficiency(raw_costs, outcomes)
    analysis = st.component_analysis(signal_outcomes, windows, fresh)
    report["score_components"] = analysis
    report["correlations"] = st.correlation_matrix(signal_outcomes, windows)
    s41 = st.derive_score_model(analysis)
    report["score_model_s41"] = {
        "weights": s41.weights,
        "penalty_codes": s41.penalty_codes,
        "name": s41.name,
    }
    report["interactions"] = st.interactions(signal_outcomes, windows)
    report["funding"] = st.funding_study(signal_outcomes, funding, windows)
    report["reversal_diagnostics"] = st.reversal_diagnostics(signal_outcomes)
    log("score model", s41)

    # --- variant studies ---
    trend = Variant("trend", families=TREND)
    studies: dict[str, list[Variant]] = {
        "baseline": [BASELINE],
        "costs": [replace(BASELINE, name=f"baseline@{c}", costs=c) for c in ("low", "high")]
        + [replace(trend, name=f"trend@{c}", costs=c) for c in ("low", "base", "high")],
        "families": [
            Variant(f"family:{st.FAMILY_SHORT[f]}|t{t}", families=(f,), threshold=float(t))
            for f in st.ALL_FAMILIES
            for t in (65, 75)
        ],
        "regimes": [
            Variant("trend|no-weak-regime", families=TREND, excluded_regimes=WEAK_REGIMES),
            Variant("all|no-weak-regime", excluded_regimes=WEAK_REGIMES),
        ],
        "entry": [
            Variant("trend|entry:close", families=TREND, entry="close"),
            Variant("trend|entry:retrace", families=TREND, entry="retrace"),
            Variant("all|entry:close", entry="close"),
            Variant("all|entry:retrace", entry="retrace"),
            Variant("all|has_zone|entry:close", entry="close", filters=("has_zone",)),
            Variant("all|has_zone|entry:zone", entry="zone", filters=("has_zone",)),
            Variant(
                "trend|has_zone|entry:close", families=TREND, entry="close", filters=("has_zone",)
            ),
            Variant(
                "trend|has_zone|entry:zone", families=TREND, entry="zone", filters=("has_zone",)
            ),
        ],
        "stops": [
            Variant(f"{n}|stop:{m}", families=f, stop=m)
            for n, f in (("trend", TREND), ("all", st.ALL_FAMILIES))
            for m in ("A", "B", "C")
        ],
        "targets": [
            Variant("trend|target:B", families=TREND, target="B"),
            Variant("trend|runner", families=TREND, runner=True),
            Variant("trend|break_even", families=TREND, break_even=True),
            Variant("all|target:B", target="B"),
            Variant("all|runner", runner=True),
            Variant("all|break_even", break_even=True),
        ],
        "score": [
            Variant(f"s41|all|t{t}", score=s41, threshold=float(t))
            for t in (60, 65, 70, 75, 80, 85)
        ]
        + [
            Variant(f"s41|trend|t{t}", families=TREND, score=s41, threshold=float(t))
            for t in (60, 65, 70, 75, 80)
        ]
        + [Variant("baseline-score|all|t60", threshold=60.0)],
        "filters": [
            Variant(f"trend|filter:{f}", families=TREND, filters=(f,))
            for f in (
                "htf_aligned",
                "swing_aligned",
                "trend_aligned",
                "not_extended",
                "discount_half",
                "vol_normal",
            )
        ],
    }
    all_variants = [v for vs in studies.values() for v in vs]
    grid = candidate_grid(s41)
    log("running", len(all_variants), "study variants +", len(grid), "candidates")
    everything = all_variants + grid
    results: dict[str, list[Any]] = {v.name: [] for v in everything}
    for _key, by_variant in st.parallel(
        st.series_phase_b, [(k, everything) for k in keys], workers
    ):
        for vname, trades in by_variant.items():
            results[vname].extend(trades)
    for trades in results.values():
        trades.sort(key=lambda s: (s.confirmed_time, s.symbol, s.timeframe))
    log("variants done")

    report["studies"] = {}
    for study, variants in studies.items():
        report["studies"][study] = {}
        for v in variants:
            trades = results[v.name]
            scoped = (
                trades
                if v.name.startswith("baseline")
                else [s for s in trades if s.timeframe in st.SIGNAL_TFS]
            )
            summary = st.summarize(
                scoped, windows, fresh, detail=study in ("baseline", "families", "regimes")
            )
            summary["version"] = v.version
            summary["definition"] = v.definition()
            if study == "score" or v.name == "baseline":
                summary["calibration"] = st.calibration(scoped, windows)
            report["studies"][study][v.name] = summary
    report["baseline_1m_10m"] = {
        tf: st.summarize(
            [s for s in results["baseline"] if s.timeframe == tf], windows, fresh, detail=False
        )
        for tf in ("1m", "10m")
    }
    ltf_tasks = []
    for m in members:
        if (m.symbol, "5m") not in keys:
            continue
        by_base = {
            base: [
                x for x in results[base] if x.symbol == m.symbol and x.timeframe in ("15m", "30m")
            ]
            for base in ("trend@base", "baseline")
        }
        ltf_tasks.append((m.symbol, by_base))
    report["ltf"] = st.ltf_study(st.parallel(st.ltf_symbol, ltf_tasks, workers), windows)

    # --- candidates: walk-forward selection + per-candidate robustness --------------------------
    report["candidates"] = {}
    for scope_name, scope in SCOPES.items():
        rows = {}
        for v in grid:
            trades = [s for s in results[v.name] if s.timeframe in scope]
            rows[v.name] = st.brief(st.summarize(trades, windows, fresh, detail=False))
        report["candidates"][scope_name] = {
            "grid": rows,
            "walk_forward_selection": walk_forward_selection(results, grid, windows, scope, fresh),
        }
    passing = [
        (scope, name)
        for scope, block in report["candidates"].items()
        for name, row in block["grid"].items()
        if row["assessment"]["status"] == "PASS"
    ]
    report["passing_candidates"] = passing
    report["robustness"] = {}
    for scope, cname in passing[:10] or []:
        trades = [s for s in results[cname] if s.timeframe in SCOPES[scope]]
        full = st.summarize(trades, windows, fresh, detail=True)
        full["calibration"] = st.calibration(trades, windows)
        report["robustness"][f"{scope}:{cname}"] = full
    report["elapsed_s"] = round(time.time() - started)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"{name}.json"
    path.write_text(json.dumps(report, indent=1, default=str))
    run_id = store.save_run(
        name,
        baseline_version=BASELINE.version,
        analysis_version=report["analysis_version"],
        metadata={
            k: report[k]
            for k in ("windows", "symbols", "coverage", "costs", "mtf_roles", "sample_rules")
        },
        results={k: v for k, v in report.items() if k not in ("symbols", "coverage")},
    )
    store.close()
    log("report", path, "research_run id", run_id, "passing", passing)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="phase41")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--skip-pass1", action="store_true")
    parser.add_argument("--symbols", nargs="*")
    parser.add_argument("--timeframes", nargs="*")
    args = parser.parse_args()
    main(args.name, args.workers, args.skip_pass1, args.symbols, args.timeframes)
