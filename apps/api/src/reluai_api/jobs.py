"""The job app shared by the API (to queue jobs) and the worker (to run them)."""

from __future__ import annotations

from procrastinate import App, Blueprint

from reluai_core.jobs import QUEUE_DEFAULT, create_job_app
from reluai_core.logging import get_logger
from reluai_core.ratelimit import purge_expired
from reluai_core.runtime import get_runtime
from reluai_core.settings import CoreSettings
from reluai_pipeline.tasks import EXECUTE_TASK
from reluai_pipeline.tasks import blueprint as pipeline_blueprint

platform_blueprint = Blueprint()
log = get_logger(__name__)


@platform_blueprint.periodic(cron="23 3 * * *", periodic_id="platform-housekeeping")
@platform_blueprint.task(name="housekeeping", queue=QUEUE_DEFAULT)
def housekeeping(timestamp: int) -> None:
    rt = get_runtime()
    with rt.db.session() as s:
        purged = purge_expired(s)
    log.info("housekeeping.done", rate_counters_purged=purged, timestamp=timestamp)


def build_job_app(settings: CoreSettings) -> App:
    return create_job_app(
        settings, {"platform": platform_blueprint, "pipeline": pipeline_blueprint}
    )


__all__ = ["EXECUTE_TASK", "build_job_app"]
