"""Background tasks: visitor/scheduled runs (CPU-leased) and housekeeping."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from procrastinate import Blueprint
from sqlalchemy import update

from reluai_core.cpu_lease import LeaseUnavailableError, cpu_lease
from reluai_core.jobs import QUEUE_DEFAULT, QUEUE_HEAVY
from reluai_core.logging import get_logger
from reluai_core.runtime import get_runtime
from reluai_pipeline.models import PipelineRun
from reluai_pipeline.runner import create_run, execute_run
from reluai_pipeline.settings import get_pipeline_settings

blueprint = Blueprint()
log = get_logger(__name__)
EXECUTE_TASK = "pipeline:execute_run"
STALE_AFTER = timedelta(hours=2)


@blueprint.task(name="execute_run", queue=QUEUE_HEAVY)
def execute_run_task(run_id: str) -> None:
    rt = get_runtime()
    rid = uuid.UUID(run_id)
    try:
        with cpu_lease(
            rt.db.engine,
            holder=f"pipeline-run:{run_id[:8]}",
            wait_seconds=rt.settings.cpu_lease_wait_seconds,
        ):
            execute_run(rt.db, get_pipeline_settings(), rid)
    except LeaseUnavailableError as exc:
        log.warning("pipeline.lease_unavailable", run_id=run_id)
        with rt.db.session() as s:
            s.execute(
                update(PipelineRun)
                .where(PipelineRun.id == rid)
                .values(
                    status="failed",
                    failure_step="queue",
                    finished_at=datetime.now(UTC),
                    error_message=f"Server busy: {exc}",
                )
            )


@blueprint.periodic(cron=get_pipeline_settings().schedule_cron, periodic_id="pipeline-scheduled")
@blueprint.task(name="scheduled_run", queue=QUEUE_DEFAULT)
def scheduled_run(timestamp: int) -> None:
    rt = get_runtime()
    run_id = create_run(rt.db, scenario="standard", trigger="scheduled")
    log.info("pipeline.scheduled_run", run_id=str(run_id), timestamp=timestamp)
    if rt.jobs is None:
        raise RuntimeError("job app not configured")
    rt.jobs.configure_task(EXECUTE_TASK).defer(run_id=str(run_id))


@blueprint.periodic(cron="*/15 * * * *", periodic_id="pipeline-expire-stale")
@blueprint.task(name="expire_stale_runs", queue=QUEUE_DEFAULT)
def expire_stale_runs(timestamp: int) -> None:
    """Fail runs stuck in queued/running (e.g. the worker restarted mid-run)."""
    rt = get_runtime()
    cutoff = datetime.now(UTC) - STALE_AFTER
    with rt.db.session() as s:
        result = s.execute(
            update(PipelineRun)
            .where(PipelineRun.status.in_(("queued", "running")), PipelineRun.queued_at < cutoff)
            .values(
                status="failed",
                failure_step="queue",
                finished_at=datetime.now(UTC),
                error_message="Run did not complete within 2 hours and was expired.",
            )
        )
    expired = int(getattr(result, "rowcount", 0) or 0)
    if expired:
        log.warning("pipeline.runs_expired", count=expired, timestamp=timestamp)
