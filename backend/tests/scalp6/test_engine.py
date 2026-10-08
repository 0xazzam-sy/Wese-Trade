"""scalp-6 engine integrity: causality / no repaint, plans, levels, selection, reasons."""

from __future__ import annotations

import random

from app.research.ltf5.data import Series
from app.scalp6.engine import (
    Evaluation,
    Profile,
    Scalp6Engine,
    TradePlan,
    allowed_families,
    choose,
)
from app.scalp6.levels import LevelBook


def synthetic(n: int = 3000, seed: int = 5) -> Series:
    rng = random.Random(seed)  # noqa: S311 - deterministic test data
    s = Series("TESTUSDT", "5m")
    price, drift = 100.0, 0.0
    for k in range(n):
        if k % 300 == 0:
            drift = rng.choice((-1, 0, 1)) * 0.0006
        o = price
        c = max(1.0, o * (1 + drift + rng.gauss(0, 0.0035)))
        h = max(o, c) * (1 + abs(rng.gauss(0, 0.002)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.002)))
        s.append(k * s.step, o, h, lo, c, 50 + rng.random() * 100)
        price = c
    return s


def run(s: Series, n: int, profile: Profile) -> list[tuple[int, int, str | None, float]]:
    eng = Scalp6Engine(profile, s.step)
    out = []
    for i in range(n):
        d = eng.update(s.t[i], s.o[i], s.h[i], s.lo[i], s.c[i], s.v[i], [(1, 0.5)])
        out.append((d.index, d.side, d.family, d.score))
    return out


def test_decisions_are_causal_and_never_repaint() -> None:
    s = synthetic()
    prof = Profile("5m", threshold=55.0)
    full = run(s, len(s), prof)
    assert any(side != 0 for _, side, _, _ in full), "the synthetic market must produce signals"
    for cut in (900, 1700, 2600):
        assert run(s, cut, prof) == full[:cut]


def test_every_signal_has_an_ordered_structural_plan_and_reasons() -> None:
    s = synthetic()
    eng = Scalp6Engine(Profile("5m", threshold=55.0), s.step)
    seen = 0
    for i in range(len(s)):
        d = eng.update(s.t[i], s.o[i], s.h[i], s.lo[i], s.c[i], s.v[i], [])
        if d.side == 0:
            continue
        seen += 1
        p = d.plan
        assert p is not None
        side = d.side
        assert side * (p.entry - p.stop) > 0  # stop on the invalidation side
        t1, t2, t3 = p.targets
        assert side * (t1 - p.entry) > 0 and side * (t2 - t1) > 0 and side * (t3 - t2) > 0
        assert p.rr[1] >= 1.0  # poor R:R is a hard blocker
        assert d.reasons and d.reasons[0] in ("استمرار الاتجاه", "اختراق بزخم", "سحب سيولة وانعكاس")
        assert 0 <= d.score <= 100
    assert seen > 0


def test_neutral_never_carries_an_actionable_side() -> None:
    s = synthetic()
    eng = Scalp6Engine(Profile("5m", threshold=99.0), s.step)
    for i in range(len(s)):
        d = eng.update(s.t[i], s.o[i], s.h[i], s.lo[i], s.c[i], s.v[i], [])
        assert d.side == 0
        if d.family is not None:
            assert "score_below_threshold" in d.blockers or d.blockers


def _plan(side: int) -> TradePlan:
    return TradePlan(
        side, 100.0, "market", 100.0, 100 - side, (101.0, 102.0, 103.0), ("a", "b", "c")
    )


def test_choose_routes_by_regime_and_applies_threshold_and_penalty() -> None:
    a = Evaluation("A", 1, 72.0, _plan(1), None, ())
    c = Evaluation("C", -1, 80.0, _plan(-1), None, ())
    adaptive = Profile("5m", adaptive=True, threshold=70.0)
    assert allowed_families(adaptive, "trending") == ("A", "B")
    assert allowed_families(adaptive, "ranging") == ("B", "C")
    pick = choose([a, c], "trending", adaptive)
    assert pick is not None and pick[0] is a and pick[3] == []
    pick = choose([a, c], "ranging", adaptive)
    assert pick is not None and pick[0] is c
    pick = choose([a, c], "transitional", adaptive)  # -10 penalty in transition
    assert pick is not None and pick[0] is c and pick[1] == 70.0
    pick = choose([a], "transitional", adaptive)
    assert pick is not None and "score_below_threshold" in pick[3]
    only_a = Profile("5m", families=("A",), adaptive=False, threshold=70.0)
    assert choose([c], "ranging", only_a) is None


def test_level_engine_counts_revisits_not_chop_and_discards_broken_back_levels() -> None:
    book = LevelBook()
    book.seed(100.0, 0, 1.0, atr=1.0)
    lv = book.levels[0]
    prev = 101.5
    # chop around the level without leaving it: no new touches
    for i, (h, lo, c) in enumerate([(100.4, 99.9, 100.35), (100.5, 99.95, 100.4)] * 3, start=1):
        book.update(i, h, lo, c, prev, atr=1.0)
        prev = c
    assert lv.touches == 1
    # leave by > 1 ATR, come back and reject: one genuine touch
    book.update(10, 102, 101.5, 101.8, prev, atr=1.0)
    book.update(11, 101.8, 99.95, 101.0, 101.8, atr=1.0)
    assert lv.touches == 2
    # decisive break below, then decisive break back above: discarded as chop
    book.update(12, 101.0, 98.8, 99.0, 101.0, atr=1.0)
    book.update(13, 101.5, 99.0, 101.3, 99.0, atr=1.0)
    assert lv not in book.levels
