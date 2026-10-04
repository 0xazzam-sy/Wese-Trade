"""Historical validation with the canonical analysis + signal engines.

    python -m app.scripts.run_backtest                     # full universe, default config
    python -m app.scripts.run_backtest --name tune1 --save-db

Writes data/backtests/<name>.json (full report) and prints a summary. Uses only data in
data/history (see app.scripts.fetch_history). Results are R-multiples, gross and net.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from app.backtesting.report import BACKTEST_DIR, build_report, run_pass1, save_cache, timed
from app.market_data.timeframes import Timeframe
from app.signal_engine.config import DEFAULT_SIGNAL_CONFIG

ALL_TFS = ["1m", "5m", "10m", "15m", "30m", "1h"]


def fmt(stats: dict[str, Any]) -> str:
    def f(v: Any, d: int = 2) -> str:
        return "—" if v is None else (f"{v:.{d}f}" if isinstance(v, float) else str(v))

    return (
        f"n={stats['entered']:>4} win={f(stats['win_rate'])} expR={f(stats['expectancy'], 3)} "
        f"PF={f(stats['profit_factor'])} DD={f(stats['max_drawdown_r'], 1)}R "
        f"totR={f(stats['total_r'], 1)} gross_expR={f(stats['gross_expectancy'], 3)} "
        f"amb={stats['ambiguous']} exp/inv={stats['expired']}/{stats['invalidated']}"
    )


def print_summary(report: dict[str, Any]) -> None:
    print("strategy_version:", report["strategy_version"])
    for part in ("dev", "holdout", "all"):
        print(f"\n== {part.upper()} ==  {fmt(report[part]['overall'])}")
        for key in ("by_timeframe", "by_symbol", "by_setup", "by_class", "by_regime"):
            for name, stats in report[part][key].items():
                print(f"  {key[3:]:>9} {name:<24} {fmt(stats)}")
        print("  calibration:")
        for row in report[part]["calibration"]:
            exp = row["expectancy"]
            print(
                f"    {row['bucket']:>7} n={row['entered']:>4} "
                f"win={'—' if row['win_rate'] is None else f'{row["win_rate"]:.2f}'} "
                f"expR={'—' if exp is None else f'{exp:.3f}'}"
            )
        print("  score monotonic:", report[part]["score_monotonic"])


async def save_db(report: dict[str, Any], name: str) -> None:
    from app.core.config import get_settings
    from app.db.session import Database
    from app.services.signal_store import save_backtest_run

    database = Database(get_settings())
    try:
        async with database.session_factory() as session:
            await save_backtest_run(session, name, report)
    finally:
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", default="baseline")
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT", "SOLUSDT"])
    parser.add_argument("--timeframes", nargs="+", default=ALL_TFS)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--save-db", action="store_true")
    args = parser.parse_args()
    config = DEFAULT_SIGNAL_CONFIG
    done = timed("pass 1 (analysis + signal replay)")
    results = run_pass1(args.symbols, [Timeframe(t) for t in args.timeframes], config, args.workers)
    done()
    save_cache(results, args.name)
    report = build_report(results, config)
    BACKTEST_DIR.mkdir(parents=True, exist_ok=True)
    (BACKTEST_DIR / f"{args.name}.json").write_text(json.dumps(report, default=str, indent=1))
    print_summary(report)
    if args.save_db:
        asyncio.run(save_db(report, args.name))


if __name__ == "__main__":
    main()
