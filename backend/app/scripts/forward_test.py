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
from dataclasses import asdict
from datetime import UTC, datetime

from app.core.config import get_settings
from app.db.session import Database
from app.forward_test import store
from app.forward_test.candidate import (
    CRITERIA,
    RESEARCH_VERSION,
    TIMEFRAMES,
    UNIVERSE,
    candidate,
    fingerprint,
    forward_version,
    frozen_config,
)
from app.market_data.okx.rest import OkxRestClient
from app.research.simulate import COSTS


async def active_symbols() -> set[str]:
    rest = OkxRestClient(get_settings().okx_rest_url)
    try:
        rows = await rest.get("/api/v5/public/instruments", {"instType": "SWAP"})
    finally:
        await rest.close()
    return {
        r["instId"].replace("-SWAP", "").replace("-", "")
        for r in rows
        if r.get("state") == "live" and r["instId"].endswith("-USDT-SWAP")
    }


async def start(notes: str) -> None:
    v = candidate()
    config = frozen_config(v)
    version = forward_version(config)
    live = await active_symbols()
    symbols = [s for s in UNIVERSE if s in live]
    missing = [s for s in UNIVERSE if s not in live]
    if missing:
        notes = f"{notes} | not active on OKX at start (excluded): {', '.join(missing)}".strip(" |")
    database = Database(get_settings())
    try:
        async with database.session_factory() as session:
            run = await store.create_run(
                session,
                version=version,
                fingerprint=fingerprint(version),
                research_version=RESEARCH_VERSION,
                config=config,
                started_at=datetime.now(UTC).replace(microsecond=0),
                symbols=symbols,
                timeframes=list(TIMEFRAMES),
                cost_model=asdict(COSTS[v.costs]),
                minimum_required_trades=CRITERIA.min_closed_trades,
                minimum_days=CRITERIA.min_days,
                notes=notes,
            )
            print(f"started run {run.id}: {version} ({fingerprint(version)})")
            print(f"started_at (UTC): {run.started_at.isoformat()}")
            print(f"symbols ({len(symbols)}): {', '.join(symbols)}")
            print(f"timeframes: {', '.join(TIMEFRAMES)}")
            if missing:
                print("excluded (inactive):", ", ".join(missing))
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
