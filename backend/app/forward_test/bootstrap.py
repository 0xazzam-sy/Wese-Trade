"""Create or resume THE forward-test run (shared by the CLI and the desktop runtime).

* An open run for the frozen version is resumed as-is (never recreated).
* Otherwise a NEW run starts with ``started_at`` = the current UTC wall clock. It is never
  backdated, and no data from another installation (e.g. a temporary container) is reused.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import asdict
from datetime import UTC, datetime

from app.core.logging import get_logger
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
from app.models.forward_test import ForwardTestRun
from app.research.simulate import COSTS

logger = get_logger(__name__)

ActiveSymbols = Callable[[], Awaitable[set[str]]]


async def okx_active_symbols(rest_url: str) -> set[str]:
    """Live OKX USDT perpetuals (public endpoint, no credentials)."""
    rest = OkxRestClient(rest_url)
    try:
        rows = await rest.get("/api/v5/public/instruments", {"instType": "SWAP"})
    finally:
        await rest.close()
    return {
        r["instId"].replace("-SWAP", "").replace("-", "")
        for r in rows
        if r.get("state") == "live" and r["instId"].endswith("-USDT-SWAP")
    }


async def create_run(
    database: Database,
    *,
    notes: str,
    active_symbols: ActiveSymbols | None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ForwardTestRun:
    v = candidate()
    config = frozen_config(v)
    version = forward_version(config)
    symbols = list(UNIVERSE)
    if active_symbols is not None:
        try:
            live = await active_symbols()
        except Exception as exc:  # offline first launch: keep the pre-registered universe
            notes = f"{notes} | OKX instrument check unavailable at start ({type(exc).__name__})"
        else:
            missing = [s for s in UNIVERSE if s not in live]
            symbols = [s for s in UNIVERSE if s in live]
            if missing:
                notes = f"{notes} | not active on OKX at start (excluded): {', '.join(missing)}"
    async with database.session_factory() as session:
        return await store.create_run(
            session,
            version=version,
            fingerprint=fingerprint(version),
            research_version=RESEARCH_VERSION,
            config=config,
            started_at=now().replace(microsecond=0),
            symbols=symbols,
            timeframes=list(TIMEFRAMES),
            cost_model=asdict(COSTS[v.costs]),
            minimum_required_trades=CRITERIA.min_closed_trades,
            minimum_days=CRITERIA.min_days,
            notes=notes.strip(" |"),
        )


async def ensure_run(
    database: Database, *, notes: str, active_symbols: ActiveSymbols | None
) -> tuple[ForwardTestRun, bool]:
    """Return (run, created). Resumes any open run; creates one only if none is open."""
    async with database.session_factory() as session:
        existing = await store.open_run(session)
    if existing is not None:
        return existing, False
    run = await create_run(database, notes=notes, active_symbols=active_symbols)
    logger.info(
        "forward_test.run_created",
        extra={"fields": {"run": run.id, "started_at": run.started_at.isoformat()}},
    )
    return run, True
