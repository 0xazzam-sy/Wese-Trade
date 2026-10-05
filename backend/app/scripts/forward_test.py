"""Start / inspect the Phase 4.2 forward test (paper only; no orders, no accounts).

    python -m app.scripts.forward_test start --notes "first prospective run"
    python -m app.scripts.forward_test status

`start` creates ONE run for the frozen strategy version with started_at = now (UTC, never
backdated). Universe symbols are checked against OKX public instruments; inactive ones
are recorded in the run notes and never get signals. Pause/resume/stop are admin actions
in the app (/forward-test) so the running service applies them immediately.
"""

from __future__ import annotations

import argparse
import asyncio

from app.core.config import get_settings
from app.db.session import Database
from app.forward_test import store
from app.forward_test.bootstrap import create_run, okx_active_symbols


async def start(notes: str) -> None:
    database = Database(get_settings())
    try:
        run = await create_run(
            database,
            notes=notes,
            active_symbols=lambda: okx_active_symbols(get_settings().okx_rest_url),
        )
        print(f"started run {run.id}: {run.strategy_version} ({run.fingerprint})")
        print(f"started_at (UTC): {run.started_at.isoformat()}")
        print(f"symbols ({len(run.symbols)}): {', '.join(run.symbols)}")
        print(f"timeframes: {', '.join(run.timeframes)}")
        if run.notes:
            print(f"notes: {run.notes}")
    finally:
        await database.dispose()


async def status() -> None:
    database = Database(get_settings())
    try:
        async with database.session_factory() as session:
            run = await store.open_run(session)
            if run is None:
                print("no open forward-test run")
                return
            signals = await store.load_signals(session, run.id)
            print(store.run_payload(run))
            print(f"confirmed signals: {len(signals)}")
    finally:
        await database.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_start = sub.add_parser("start")
    p_start.add_argument("--notes", default="")
    sub.add_parser("status")
    args = parser.parse_args()
    asyncio.run(start(args.notes) if args.cmd == "start" else status())
