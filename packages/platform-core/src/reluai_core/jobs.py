"""Background jobs on PostgreSQL (procrastinate) — no Redis.

Each project declares its tasks on a ``procrastinate.Blueprint``; the composition root
(``reluai_api``) collects the blueprints into one app used by both the API (to queue jobs)
and the worker (to run them).
"""

from __future__ import annotations

from collections.abc import Mapping

from procrastinate import App, Blueprint, PsycopgConnector
from sqlalchemy import Engine, text

from reluai_core.settings import CoreSettings

QUEUE_DEFAULT = "default"
QUEUE_HEAVY = "heavy"  # CPU-bound jobs; each also takes the global CPU lease


class QueueFullError(RuntimeError):
    """Too many jobs are already waiting; the caller should retry later (HTTP 429)."""


def create_job_app(settings: CoreSettings, blueprints: Mapping[str, Blueprint]) -> App:
    connector = PsycopgConnector(
        conninfo=settings.libpq_dsn,
        min_size=1,
        max_size=4,
        kwargs={"application_name": f"{settings.service_name}-jobs"},
    )
    app = App(connector=connector)
    for namespace, blueprint in blueprints.items():
        app.add_tasks_from(blueprint, namespace=namespace)
    return app


def queue_depth(engine: Engine, queue: str) -> int:
    """Jobs waiting or running on ``queue`` (0 if the job tables do not exist yet)."""
    sql = text(
        "SELECT count(*) FROM procrastinate_jobs "
        "WHERE queue_name = :q AND status IN ('todo', 'doing')"
    )
    with engine.connect() as conn:
        exists = conn.execute(text("SELECT to_regclass('public.procrastinate_jobs')")).scalar()
        if exists is None:
            return 0
        return int(conn.execute(sql, {"q": queue}).scalar_one())
