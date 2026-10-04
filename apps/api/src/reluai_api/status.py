"""Public status summary for the website's /status page (no internal detail)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select

from reluai_core.cpu_lease import lease_status
from reluai_core.db import DatabaseDep
from reluai_core.logging import get_logger
from reluai_pipeline.models import PipelineRun

router = APIRouter(tags=["status"])
Health = Literal["operational", "degraded", "down"]
log = get_logger(__name__)


class ComponentStatus(BaseModel):
    name: str
    status: Literal["operational", "degraded", "down"]
    detail: str


class StatusOut(BaseModel):
    status: Literal["operational", "degraded", "down"]
    version: str
    environment: str
    checked_at: datetime
    components: list[ComponentStatus]
    busy_with: str | None


@router.get("/status", response_model=StatusOut)
def get_status(request: Request, db: DatabaseDep) -> StatusOut:
    core = request.app.state.core_settings
    components: list[ComponentStatus] = [
        ComponentStatus(name="API", status="operational", detail="Serving requests")
    ]
    busy: str | None = None
    try:
        db.ping()
        components.append(
            ComponentStatus(name="Database", status="operational", detail="PostgreSQL reachable")
        )
        with db.session() as s:
            last = s.scalars(
                select(PipelineRun)
                .where(PipelineRun.finished_at.is_not(None))
                .order_by(PipelineRun.finished_at.desc())
                .limit(1)
            ).first()
        if last is None:
            components.append(
                ComponentStatus(name="Pipeline", status="degraded", detail="No runs recorded yet")
            )
        else:
            age_h = (
                (datetime.now(UTC) - last.finished_at).total_seconds() / 3600
                if last.finished_at
                else 0
            )
            ok = age_h < 13  # scheduled every 6 hours; allow one missed run
            components.append(
                ComponentStatus(
                    name="Pipeline",
                    status="operational" if ok else "degraded",
                    detail=f"Last run {last.status} {age_h:.1f} h ago",
                )
            )
        busy = lease_status(db.engine).holder
    except Exception as exc:
        log.warning("status.database_unreachable", error=type(exc).__name__)
        components.append(
            ComponentStatus(name="Database", status="down", detail="PostgreSQL unreachable")
        )
    worst: Health = (
        "down"
        if any(c.status == "down" for c in components)
        else "degraded"
        if any(c.status == "degraded" for c in components)
        else "operational"
    )
    return StatusOut(
        status=worst,
        version=core.version,
        environment=core.environment.value,
        checked_at=datetime.now(UTC),
        components=components,
        busy_with=busy,
    )
