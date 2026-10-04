"""Parallel research pass 1 over the research store, with a versioned on-disk cache.

Each (symbol, timeframe) series is collected independently in a worker process (safe:
no shared state). The cache key contains the baseline strategy version and the data
range, so cached results are reused only for identical code config + data.
"""

from __future__ import annotations

import pickle
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from app.analysis.multi_timeframe.context import context_timeframes
from app.market_data.timeframes import Timeframe
from app.research.collect import SeriesResearch, collect
from app.research.store import RESEARCH_DIR, ResearchStore
from app.signal_engine.config import DEFAULT_SIGNAL_CONFIG, strategy_version

PASS1_DIR = RESEARCH_DIR / "pass1"
ORDER = {"1m": 0, "5m": 1, "10m": 2, "15m": 3, "30m": 4, "1h": 5}


def cache_path(symbol: str, tf: str, root: Path = PASS1_DIR) -> Path:
    return root / f"{symbol}_{tf}.pkl"


def _key(symbol: str, tf: Timeframe, store: ResearchStore) -> str:
    source = tf.source if tf.is_synthetic else tf
    cov = store.coverage(symbol, source)
    ctx = [store.coverage(symbol, c) for c in context_timeframes(tf)]
    parts = [
        strategy_version(DEFAULT_SIGNAL_CONFIG),
        "collect-v1",
        f"{cov.first_ms}-{cov.last_ms}-{cov.candles}",
    ]
    parts += [f"{c.timeframe}:{c.first_ms}-{c.last_ms}-{c.candles}" for c in ctx]
    return "|".join(parts)


def _job(args: tuple[str, str, float, int | None]) -> str:
    symbol, tf_value, tick, since_ms = args
    tf = Timeframe(tf_value)
    store = ResearchStore()
    try:
        key = _key(symbol, tf, store)
        path = cache_path(symbol, tf_value)
        if path.exists():
            with path.open("rb") as fh:
                if pickle.load(fh) == key:  # noqa: S301 - our own local cache
                    return f"{symbol} {tf_value}: cached"
        candles = store.load(symbol, tf, start_ms=since_ms)
        context = {c: store.load(symbol, c, start_ms=since_ms) for c in context_timeframes(tf)}
    finally:
        store.close()
    result = collect(symbol, tf, candles, context, tick=tick)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as fh:
        pickle.dump(key, fh, protocol=pickle.HIGHEST_PROTOCOL)
        pickle.dump(result, fh, protocol=pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)
    hyps = sum(len(t.hyps) for t in result.triggers)
    n_bars, n_trig = len(result.bars), len(result.triggers)
    return f"{symbol} {tf_value}: {n_bars} bars, {n_trig} triggers, {hyps} hypotheses"


def run_pass1(jobs: list[tuple[str, str, float, int | None]], workers: int = 4) -> list[str]:
    jobs = sorted(jobs, key=lambda j: ORDER[j[1]])
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_job, jobs))


def load_series(symbol: str, tf: str) -> SeriesResearch:
    with cache_path(symbol, tf).open("rb") as fh:
        pickle.load(fh)  # noqa: S301 - key; our own local cache
        result: SeriesResearch = pickle.load(fh)  # noqa: S301
        return result
