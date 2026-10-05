"""Backtest orchestration + report (dev/holdout split, groupings, calibration)."""

from __future__ import annotations

import pickle
import time
from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.analysis.multi_timeframe.context import context_timeframes
from app.backtesting import history
from app.backtesting.metrics import compute, group
from app.backtesting.runner import ReplayResult, replay, simulate
from app.core.runtime import BACKEND_DIR
from app.market_data.timeframes import Timeframe
from app.signal_engine.calibration import calibration_table, monotonic_score
from app.signal_engine.config import SignalConfig, strategy_version
from app.signal_engine.models import Signal
from app.utils.time import utc_isoformat, utc_now

BACKTEST_DIR = BACKEND_DIR / "data" / "backtests"
DEV_FRACTION = 0.7
TICKS = {"BTCUSDT": 0.1, "ETHUSDT": 0.01, "SOLUSDT": 0.01}


def _replay_job(args: tuple[str, str, SignalConfig, float]) -> ReplayResult:
    symbol, tf_value, config, tick = args
    tf = Timeframe(tf_value)
    candles = history.load(symbol, tf)
    context = {ctf: history.load(symbol, ctf) for ctf in context_timeframes(tf)}
    return replay(symbol, tf, candles, context, tick=tick, config=config)


def run_pass1(
    symbols: list[str], timeframes: list[Timeframe], config: SignalConfig, workers: int = 4
) -> list[ReplayResult]:
    jobs = [(s, tf.value, config, TICKS.get(s, 0.01)) for s in symbols for tf in timeframes]
    # biggest first for better packing
    jobs.sort(key=lambda j: {"1m": 0, "5m": 1, "10m": 2, "15m": 3, "30m": 4, "1h": 5}[j[1]])
    with ProcessPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_replay_job, jobs))


def split_time(result: ReplayResult, fraction: float = DEV_FRACTION) -> int:
    return int(result.first_time + fraction * (result.last_time - result.first_time))


def segment(results: Iterable[tuple[ReplayResult, list[Signal]]], part: str) -> list[Signal]:
    out: list[Signal] = []
    for result, signals in results:
        cut = split_time(result)
        out += [s for s in signals if (s.confirmed_time < cut) == (part == "dev")]
    return out


def summarize(signals: list[Signal]) -> dict[str, Any]:
    calibration = calibration_table(signals)
    return {
        "overall": compute(signals).as_dict(),
        "by_symbol": group(signals, lambda s: s.symbol),
        "by_timeframe": group(signals, lambda s: s.timeframe),
        "by_setup": group(signals, lambda s: s.family.value),
        "by_regime": group(signals, lambda s: s.regime or "unknown"),
        "by_class": group(signals, lambda s: s.signal_class.value),
        "by_side": group(signals, lambda s: s.side.value),
        "by_series": group(signals, lambda s: f"{s.symbol} {s.timeframe}"),
        "calibration": calibration,
        "score_monotonic": monotonic_score(calibration),
    }


def build_report(
    results: list[ReplayResult],
    config: SignalConfig,
    signals_by_series: list[list[Signal]] | None = None,
) -> dict[str, Any]:
    pairs = list(zip(results, signals_by_series or [r.signals for r in results], strict=True))
    dev, holdout = segment(pairs, "dev"), segment(pairs, "holdout")
    return {
        "strategy_version": strategy_version(config),
        "config": asdict(config),
        "generated_at": utc_isoformat(utc_now()),
        "dev_fraction": DEV_FRACTION,
        "data": [
            {
                "symbol": r.symbol,
                "timeframe": r.timeframe,
                "candles": len(r.bars),
                "from": r.first_time,
                "to": r.last_time,
                "split": split_time(r),
                "triggers": r.triggers,
                "suppressed": r.suppressed,
            }
            for r in results
        ],
        "all": summarize(dev + holdout),
        "dev": summarize(dev),
        "holdout": summarize(holdout),
    }


def resimulate(results: list[ReplayResult], config: SignalConfig) -> list[list[Signal]]:
    return [simulate(r, config) for r in results]


def save_cache(results: list[ReplayResult], name: str) -> Path:
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    path = BACKTEST_DIR / f"{name}.pass1.pkl"
    with path.open("wb") as fh:
        pickle.dump(results, fh)
    return path


def load_cache(name: str) -> list[ReplayResult]:
    with (BACKTEST_DIR / f"{name}.pass1.pkl").open("rb") as fh:
        results: list[ReplayResult] = pickle.load(fh)  # noqa: S301 - written by this tool
        return results


def timed(label: str) -> Any:
    start = time.monotonic()

    def done() -> None:
        print(f"{label}: {time.monotonic() - start:.0f}s", flush=True)

    return done
