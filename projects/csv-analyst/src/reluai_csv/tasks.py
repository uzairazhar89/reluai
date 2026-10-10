"""Background jobs: the periodic evaluation run and query-log retention."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from procrastinate import Blueprint
from sqlalchemy import delete

from reluai_core.cpu_lease import LeaseUnavailableError, cpu_lease
from reluai_core.jobs import QUEUE_DEFAULT
from reluai_core.logging import get_logger
from reluai_core.runtime import get_runtime
from reluai_csv.models import QueryLog
from reluai_csv.settings import get_csv_settings

blueprint = Blueprint()
log = get_logger(__name__)
QUERY_LOG_RETENTION = timedelta(days=90)


@blueprint.periodic(cron="41 */6 * * *", periodic_id="csv-evaluation")
@blueprint.task(name="csv_evaluation", queue=QUEUE_DEFAULT)
def csv_evaluation(timestamp: int) -> None:
    """Re-run the question sets so the published results always come from this server."""
    from reluai_csv.evaluation import run_evaluation

    rt = get_runtime()
    try:
        # About 65 scans of the 1.07M-row table: brief, but heavy enough to share the
        # global lease with pipeline runs (ADR-0003).
        with cpu_lease(
            rt.db.engine,
            holder="csv-evaluation",
            wait_seconds=rt.settings.cpu_lease_wait_seconds,
        ):
            run_evaluation(get_csv_settings(), record=True, db=rt.db)
    except FileNotFoundError:
        log.warning("csv.evaluation_skipped", reason="bundled dataset not built")
    except LeaseUnavailableError:
        log.warning("csv.evaluation_skipped", reason="cpu lease busy")
    with rt.db.session() as s:
        s.execute(delete(QueryLog).where(QueryLog.ts < datetime.now(UTC) - QUERY_LOG_RETENTION))
    log.info("csv.evaluation_task_done", timestamp=timestamp)
