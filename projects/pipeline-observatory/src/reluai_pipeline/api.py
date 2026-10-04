"""Public API of the Data Pipeline Observatory (mounted at ``/api/pipeline``)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from reluai_core.db import DatabaseDep
from reluai_core.errors import ProblemError
from reluai_core.http import client_ip
from reluai_core.ratelimit import visitor_key
from reluai_pipeline import service
from reluai_pipeline.rules import REASONS
from reluai_pipeline.scenarios import SCENARIOS
from reluai_pipeline.schemas import (
    DropOut,
    QuarantinePage,
    RunAccepted,
    RunDetailOut,
    RunOut,
    RunRequest,
    ScenarioOut,
    SummaryOut,
)
from reluai_pipeline.settings import PipelineSettings, get_pipeline_settings

router = APIRouter(tags=["pipeline"])
SettingsDep = Annotated[PipelineSettings, Depends(get_pipeline_settings)]
Deferrer = Callable[[uuid.UUID], None]


def get_deferrer(request: Request) -> Deferrer:
    deferrer: Deferrer = request.app.state.pipeline_deferrer
    return deferrer


@router.get("/summary", response_model=SummaryOut)
def get_summary(db: DatabaseDep, settings: SettingsDep) -> SummaryOut:
    """Dashboard tiles: last run, last success, totals, recent trend and queue state."""
    return service.summary(db, settings)


@router.get("/runs", response_model=list[RunOut])
def get_runs(db: DatabaseDep, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[RunOut]:
    return service.list_runs(db, limit)


@router.get("/runs/{run_id}", response_model=RunDetailOut)
def get_run(run_id: uuid.UUID, db: DatabaseDep) -> RunDetailOut:
    detail = service.run_detail(db, run_id)
    if detail is None:
        raise ProblemError(404, "Run not found", code="run_not_found")
    return detail


@router.get("/runs/{run_id}/quarantine", response_model=QuarantinePage)
def get_quarantine(
    run_id: uuid.UUID,
    db: DatabaseDep,
    reason: Annotated[str | None, Query(pattern=r"^[a-z_]{3,40}$")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=20_000)] = 0,
) -> QuarantinePage:
    return service.quarantine_page(db, run_id, reason=reason, limit=limit, offset=offset)


@router.post("/runs", response_model=RunAccepted, status_code=status.HTTP_202_ACCEPTED)
def post_run(
    body: RunRequest,
    request: Request,
    db: DatabaseDep,
    settings: SettingsDep,
    defer: Annotated[Deferrer, Depends(get_deferrer)],
) -> RunAccepted:
    """Queue a pipeline run. Limited per visitor and by overall queue capacity."""
    secret = request.app.state.core_settings.visitor_hash_secret.get_secret_value()
    visitor = visitor_key(client_ip(request), secret)
    try:
        run_id, pending = service.admit_visitor_run(
            db, settings, scenario=body.scenario, visitor=visitor, defer=defer
        )
    except service.UnknownScenarioError as exc:
        raise ProblemError(
            400, f"Unknown scenario '{body.scenario}'", code="unknown_scenario"
        ) from exc
    except service.RunQuotaExceededError as exc:
        raise ProblemError(
            429,
            f"Limit of {settings.visitor_runs_per_hour} runs per hour reached. "
            "Recent runs are still visible on the dashboard.",
            code="quota_exceeded",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except service.RunQueueFullError as exc:
        raise ProblemError(
            429,
            "The pipeline queue is full right now; try again in a minute.",
            code="queue_full",
            headers={"Retry-After": "60"},
        ) from exc
    return RunAccepted(run_id=run_id, status="queued", pending_runs=pending)


@router.get("/scenarios", response_model=list[ScenarioOut])
def get_scenarios() -> list[ScenarioOut]:
    return [
        ScenarioOut(
            id=s.id,
            title=s.title,
            description=s.description,
            simulated=s.simulated,
            expected=s.expected,
        )
        for s in SCENARIOS.values()
    ]


@router.get("/drops", response_model=list[DropOut])
def get_drops(db: DatabaseDep, settings: SettingsDep) -> list[DropOut]:
    return service.drops(db, settings)


@router.get("/reasons")
def get_reasons() -> list[dict[str, str]]:
    """Every reason code the validator can assign, with its explanation."""
    return [
        {
            "code": r.code,
            "label": r.label,
            "severity": r.severity.value,
            "explanation": r.explanation,
        }
        for r in REASONS.values()
    ]
