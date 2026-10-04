"""EXPLORATORY trend-continuation refinement (Phase 4.1, disclosed as post-hoc).

The dimensions of this grid (retrace entry, runner exit, not-extended filter) were
chosen AFTER seeing the main study's validation results, so this grid can never count as
a clean historical pass. Selection inside it still uses DEVELOPMENT data only (walk-
forward), and full robustness tables are produced, so the reader can judge how much of
the apparent improvement survives an honest selection procedure.

    python -m app.scripts.research_refine --name phase41   (after run_research)
"""

from __future__ import annotations

import argparse
import itertools
import json
import time
from typing import Any

from app.research import studies as st
from app.research import universe
from app.research.simulate import Variant
from app.research.store import RESEARCH_DIR
from app.research.walkforward import Window
from app.scripts.run_research import SCOPES, TREND, WEAK_REGIMES, walk_forward_selection


def grid() -> list[Variant]:
    out = []
    for entry, runner, filt, thr, regimes in itertools.product(
        ("base", "retrace"),
        (False, True),
        ((), ("not_extended",)),
        (70.0, 75.0, 80.0),
        ((), WEAK_REGIMES),
    ):
        name = (
            f"refine:trend|{entry}|{'runner' if runner else 'tpA'}|"
            f"{'not_ext' if filt else 'nofilter'}|t{int(thr)}|{'noweak' if regimes else 'allreg'}"
        )
        out.append(
            Variant(
                name,
                families=TREND,
                entry=entry,
                runner=runner,
                filters=filt,
                threshold=thr,
                excluded_regimes=regimes,
                notes="exploratory post-hoc refinement grid",
            )
        )
    return out


def main(name: str, workers: int) -> None:
    path = RESEARCH_DIR / "reports" / f"{name}.json"
    report = json.loads(path.read_text())
    windows = [Window(**w) for w in report["windows"]]
    fresh = frozenset(report["fresh_symbols"])
    keys = [(m.symbol, tf) for m in universe.load() for tf in st.SIGNAL_TFS]
    variants = grid()
    results: dict[str, list[Any]] = {v.name: [] for v in variants}
    for _key, by_variant in st.parallel(st.series_phase_b, [(k, variants) for k in keys], workers):
        for vname, trades in by_variant.items():
            results[vname].extend(trades)
    for trades in results.values():
        trades.sort(key=lambda s: (s.confirmed_time, s.symbol, s.timeframe))
    out: dict[str, Any] = {"note": __doc__, "grid": {}, "selection": {}, "details": {}}
    for scope_name, scope in SCOPES.items():
        rows = {}
        for v in variants:
            trades = [s for s in results[v.name] if s.timeframe in scope]
            rows[v.name] = st.brief(st.summarize(trades, windows, fresh, detail=False))
        out["grid"][scope_name] = rows
        out["selection"][scope_name] = walk_forward_selection(
            results, variants, windows, scope, fresh
        )
    # full robustness tables for the variants the selection actually picked
    picked = {
        (scope, w["chosen"])
        for scope, sel in out["selection"].items()
        for w in sel["per_window"]
        if w.get("chosen")
    }
    for scope, vname in sorted(picked):
        trades = [s for s in results[vname] if s.timeframe in SCOPES[scope]]
        full = st.summarize(trades, windows, fresh, detail=True)
        full["calibration"] = st.calibration(trades, windows)
        out["details"][f"{scope}:{vname}"] = full
    report["exploratory_refinement"] = out
    path.write_text(json.dumps(report, indent=1, default=str))
    print(time.strftime("%H:%M:%S"), "refinement saved", len(variants), "variants")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="phase41")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    main(args.name, args.workers)
