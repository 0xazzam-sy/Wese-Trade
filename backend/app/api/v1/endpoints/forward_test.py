"""Forward-test routes (Phase 4.2). Read-only for the frozen strategy: there is NO endpoint
that edits weights, thresholds, stops, targets or filters. Admins may only pause, resume
or stop a run. Signals are analytical paper results, never trading instructions."""

from __future__ import annotations

import csv
import io
import json
import time
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import Resources, SessionDep, get_current_user, require_roles
from app.forward_test import store
from app.forward_test.candidate import CRITERIA, DISPLAY_NAME, frozen_config
from app.forward_test.metrics import assess, closed_trades, summary
from app.forward_test.service import DISCLAIMER_AR, STATUS_AR, ForwardTestService
from app.models.forward_test import ForwardTestRun
from app.models.user import UserRole

router = APIRouter(
    prefix="/forward-test", tags=["forward-test"], dependencies=[Depends(get_current_user)]
)
analyst = Depends(require_roles(UserRole.ADMIN, UserRole.ANALYST))
admin = Depends(require_roles(UserRole.ADMIN))


class Note(BaseModel):
    note: str = Field(default="", max_length=500)


def _service(resources: Resources) -> ForwardTestService:
    if resources.forward_test is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="forward_test_disabled")
    return resources.forward_test


Service = Annotated[ForwardTestService, Depends(_service)]


async def _run(session: SessionDep, run_id: int) -> ForwardTestRun:
    run = await session.get(ForwardTestRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="forward_test_run_not_found")
    return run


def _elapsed_days(run: ForwardTestRun) -> float:
    end = run.stopped_at.timestamp() if run.stopped_at else time.time()
    return max(0.0, (end - run.started_at.timestamp()) / 86400)


async def _metrics(session: SessionDep, run: ForwardTestRun) -> dict[str, Any]:
    signals = await store.load_signals(session, run.id)
    out = summary(signals, CRITERIA)
    verdict = assess(signals, _elapsed_days(run), CRITERIA)
    out["assessment"] = {"verdict": verdict.verdict, "reasons": list(verdict.reasons)}
    out["elapsed_days"] = round(_elapsed_days(run), 2)
    out["criteria"] = asdict(CRITERIA)
    return out


async def _latest_run(session: SessionDep) -> ForwardTestRun | None:
    return (
        (await session.execute(select(ForwardTestRun).order_by(ForwardTestRun.id.desc())))
        .scalars()
        .first()
    )


@router.get("/status")
async def forward_status(session: SessionDep, service: Service) -> dict[str, Any]:
    """Compact card for the dashboard (every authenticated user)."""
    run = await _latest_run(session)
    base: dict[str, Any] = {
        "name": DISPLAY_NAME,
        "version": service.version,
        "fingerprint": service.fingerprint,
        "disclaimer_ar": DISCLAIMER_AR,
        "health": service.health()["state"],
    }
    if run is None:
        return {**base, "run": None}
    signals = await store.load_signals(session, run.id)
    closed = closed_trades(signals)
    net = [s.net_r for s in closed if s.net_r is not None]
    return {
        **base,
        "run": {
            "id": run.id,
            "status": run.status,
            "status_ar": STATUS_AR.get(run.status, run.status),
            "started_at": run.started_at.isoformat(),
            "strategy_version": run.strategy_version,
            "fingerprint": run.fingerprint,
        },
        "confirmed_signals": len(signals),
        "closed_trades": len(closed),
        "net_expectancy_r": round(sum(net) / len(net), 4) if net else None,
        "minimum_required_trades": run.minimum_required_trades,
    }


@router.get("/config", dependencies=[analyst])
async def forward_config(service: Service) -> dict[str, Any]:
    """The frozen configuration of the CODE (compare with a run's stored config)."""
    return {
        "version": service.version,
        "fingerprint": service.fingerprint,
        "config": frozen_config(),
    }


@router.get("/health", dependencies=[analyst])
async def forward_health(service: Service) -> dict[str, Any]:
    return service.health()


@router.get("/runs", dependencies=[analyst])
async def list_runs(session: SessionDep) -> dict[str, Any]:
    rows = (
        await session.execute(select(ForwardTestRun).order_by(ForwardTestRun.id.desc()))
    ).scalars()
    return {"items": [store.run_payload(r) for r in rows]}


@router.get("/runs/{run_id}", dependencies=[analyst])
async def get_run(run_id: int, session: SessionDep, service: Service) -> dict[str, Any]:
    run = await _run(session, run_id)
    payload = store.run_payload(run)
    payload["status_ar"] = STATUS_AR.get(run.status, run.status)
    payload["config"] = run.config
    payload["metrics"] = await _metrics(session, run)
    payload["config_matches_code"] = run.strategy_version == service.version
    payload["health"] = service.health() if service.run and service.run.id == run.id else None
    payload["disclaimer_ar"] = DISCLAIMER_AR
    return payload


@router.get("/runs/{run_id}/signals", dependencies=[analyst])
async def run_signals(
    run_id: int,
    session: SessionDep,
    symbol: str | None = None,
    timeframe: str | None = None,
    side: str | None = None,
    state: str | None = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> dict[str, Any]:
    await _run(session, run_id)
    rows = await store.signal_rows(
        session, run_id, symbol=symbol, timeframe=timeframe, side=side, state=state, limit=limit
    )
    outs = await store.outcomes(session, run_id)
    return {"items": [store.signal_row_payload(r, outs.get(r.id)) for r in rows]}


@router.get("/runs/{run_id}/checkpoints", dependencies=[analyst])
async def run_checkpoints(run_id: int, session: SessionDep) -> dict[str, Any]:
    await _run(session, run_id)
    return {"items": await store.checkpoints(session, run_id)}


EXPORT_COLUMNS = (
    "signal_id",
    "strategy_version",
    "symbol",
    "timeframe",
    "side",
    "family",
    "score",
    "regime",
    "confirmed_at",
    "entry_model",
    "entry",
    "stop",
    "tp1",
    "tp2",
    "tp3",
    "state",
    "entered_at",
    "entry_price",
    "closed_at",
    "targets_hit",
    "ambiguous",
    "holding_bars",
    "gross_r",
    "net_r",
    "fees_r",
    "slippage_r",
    "exit_reason",
)


@router.get("/runs/{run_id}/export", dependencies=[analyst])
async def export_run(
    run_id: int,
    session: SessionDep,
    format: Annotated[str, Query(pattern="^(json|csv)$")] = "json",
) -> Response:
    """Run metadata + every signal with its outcome. Contains no secrets."""
    run = await _run(session, run_id)
    rows = await store.signal_rows(session, run_id, limit=None)
    outs = await store.outcomes(session, run_id)
    items = [store.signal_row_payload(r, outs.get(r.id)) for r in reversed(rows)]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    name = f"forward-test-run{run.id}-{stamp}"
    if format == "csv":
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        meta = (
            f"# run={run.id} version={run.strategy_version} "
            f"started_at={run.started_at.isoformat()} status={run.status}"
        )
        writer.writerow([meta])
        writer.writerow(EXPORT_COLUMNS)
        for item in items:
            writer.writerow([item.get(c) for c in EXPORT_COLUMNS])
        return Response(
            buffer.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
        )
    body = {
        "run": {**store.run_payload(run), "config": run.config},
        "metrics": await _metrics(session, run),
        "checkpoints": await store.checkpoints(session, run_id),
        "signals": items,
    }
    return Response(
        json.dumps(body, ensure_ascii=False, indent=1, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{name}.json"'},
    )


async def _control(
    service: ForwardTestService, run_id: int, target: str, note: str
) -> dict[str, Any]:
    if service.run is None or service.run.id != run_id:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="run_not_loaded_by_service")
    try:
        return await service.set_status(target, note or f"admin: {target}")
    except store.InvalidRunTransitionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.post("/runs/{run_id}/pause", dependencies=[admin])
async def pause_run(run_id: int, body: Note, service: Service) -> dict[str, Any]:
    return await _control(service, run_id, "paused", body.note)


@router.post("/runs/{run_id}/resume", dependencies=[admin])
async def resume_run(run_id: int, body: Note, service: Service) -> dict[str, Any]:
    return await _control(service, run_id, "forward_testing", body.note)


@router.post("/runs/{run_id}/stop", dependencies=[admin])
async def stop_run(run_id: int, body: Note, service: Service) -> dict[str, Any]:
    return await _control(service, run_id, "stopped", body.note)
