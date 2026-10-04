"""Background worker entry point (``reluai worker``)."""

from __future__ import annotations

from reluai_api.jobs import build_job_app
from reluai_core.db import Database
from reluai_core.jobs import QUEUE_DEFAULT, QUEUE_HEAVY
from reluai_core.logging import configure_logging, get_logger
from reluai_core.runtime import Runtime, set_runtime
from reluai_core.settings import get_core_settings


def run_worker(concurrency: int = 2) -> None:
    core = get_core_settings()
    configure_logging(level=core.log_level, json=core.json_logs)
    db = Database(core, application_name=f"{core.service_name}-worker")
    jobs = build_job_app(core)
    set_runtime(Runtime(settings=core, db=db, jobs=jobs))
    get_logger(__name__).info(
        "worker.starting",
        queues=[QUEUE_HEAVY, QUEUE_DEFAULT],
        concurrency=concurrency,
        version=core.version,
    )
    try:
        jobs.run_worker(
            queues=[QUEUE_HEAVY, QUEUE_DEFAULT],
            concurrency=concurrency,
            name=f"{core.service_name}-worker",
            delete_jobs="successful",
            shutdown_graceful_timeout=30,
        )
    finally:
        db.dispose()
