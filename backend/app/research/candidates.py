"""Research grids whose variants may become forward-test candidates.

`grid()` is the Phase 4.1 EXPLORATORY trend refinement grid (docs/research.md §13). It
lives here (not in a script) so the forward test can load the exact definition; the
variant's version hash proves the definition is unchanged.
"""

from __future__ import annotations

import itertools

from app.research.simulate import Variant

TREND = ("TREND_CONTINUATION",)
WEAK_REGIMES = ("range", "transitional")


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


def by_version(version: str) -> Variant:
    found = [v for v in grid() if v.version == version]
    if len(found) != 1:
        raise LookupError(f"research variant {version} not found (definition changed?)")
    return found[0]
