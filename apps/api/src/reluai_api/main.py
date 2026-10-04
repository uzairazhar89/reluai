"""FastAPI composition root: mounts the platform services and every project module."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI

from reluai_api import contact, status
from reluai_api.jobs import EXECUTE_TASK, build_job_app
from reluai_core import health, metrics
from reluai_core.db import Database
from reluai_core.errors import install_error_handlers
from reluai_core.http import BodySizeLimitMiddleware, RequestContextMiddleware
from reluai_core.logging import configure_logging
from reluai_core.runtime import Runtime, set_runtime
from reluai_core.settings import CoreSettings, get_core_settings
from reluai_pipeline import api as pipeline_api
from reluai_pipeline.sources import crm

API_DESCRIPTION = """
Backend for [reluai.cloud](https://reluai.cloud) — portfolio demonstrations running on a
2-vCPU / 8 GB VPS. All demos work without paid APIs.
"""


def create_app(
    core: CoreSettings | None = None,
    *,
    pipeline_deferrer: Callable[[uuid.UUID], None] | None = None,
) -> FastAPI:
    core = core or get_core_settings()
    configure_logging(level=core.log_level, json=core.json_logs)
    db = Database(core, application_name=f"{core.service_name}-api")
    jobs = build_job_app(core)

    # The API only defers jobs. Its connection pool to the queue opens in the background, so
    # the API still starts (and reports the problem) if PostgreSQL is briefly unavailable.
    uses_queue = pipeline_deferrer is None

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        set_runtime(Runtime(settings=core, db=db, jobs=jobs))
        if uses_queue:
            jobs.open()
        try:
            yield
        finally:
            if uses_queue:
                jobs.close()
            db.dispose()

    app = FastAPI(
        title="reluai.cloud API",
        version=core.version,
        description=API_DESCRIPTION,
        lifespan=lifespan,
        docs_url="/api/docs" if core.docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if core.docs_enabled else None,
    )
    app.state.core_settings = core
    app.state.db = db
    app.state.jobs = jobs
    app.state.pipeline_deferrer = pipeline_deferrer or (
        lambda run_id: jobs.configure_task(EXECUTE_TASK).defer(run_id=str(run_id))
    )

    install_error_handlers(app)
    app.add_middleware(
        BodySizeLimitMiddleware,
        default_limit=core.max_request_body_bytes,
        prefix_limits={"/api/pipeline": 16 * 1024, "/api/contact": 16 * 1024},
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    app.include_router(metrics.router)
    app.include_router(status.router, prefix="/api")
    app.include_router(contact.router, prefix="/api")
    app.include_router(pipeline_api.router, prefix="/api/pipeline")
    app.include_router(crm.router, prefix="/internal/crm")
    return app
