"""Background job: run the benchmark suite daily, so published numbers come from this server."""

from __future__ import annotations

from procrastinate import Blueprint

from reluai_bench.benchmark import NotBuiltError, run_suite
from reluai_bench.service import record_run
from reluai_bench.settings import get_bench_settings
from reluai_core.cpu_lease import LeaseUnavailableError, cpu_lease
from reluai_core.jobs import QUEUE_DEFAULT
from reluai_core.logging import get_logger
from reluai_core.runtime import get_runtime

blueprint = Blueprint()
log = get_logger(__name__)


@blueprint.periodic(cron="7 5 * * *", periodic_id="bench-run")
@blueprint.task(name="run", queue=QUEUE_DEFAULT)
def run(timestamp: int) -> None:
    """About two minutes of CPU: two models × three variants × two thread counts."""
    rt = get_runtime()
    settings = get_bench_settings()
    try:
        with cpu_lease(rt.db.engine, holder="bench-run", wait_seconds=settings.lease_wait_seconds):
            result = run_suite(settings)
    except LeaseUnavailableError:
        log.warning("bench.run_skipped", reason="cpu lease busy")
        return
    except NotBuiltError:
        log.warning("bench.run_skipped", reason="models not built")
        return
    row = record_run(rt.db, result, label="scheduled")
    log.info("bench.run_done", run=str(row.id), seconds=row.duration_seconds)
