"""Liveness and readiness probes (internal only — nginx does not expose them)."""

from __future__ import annotations

import shutil
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from reluai_core.db import Database
from reluai_core.logging import get_logger
from reluai_core.settings import CoreSettings

router = APIRouter(include_in_schema=False)
log = get_logger(__name__)


@router.get("/healthz")
def healthz() -> dict[str, str]:
    """The process is up and serving requests."""
    return {"status": "ok"}


def readiness(db: Database, settings: CoreSettings) -> tuple[bool, dict[str, Any]]:
    checks: dict[str, Any] = {}
    ok = True
    try:
        with db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            version = conn.execute(
                text("SELECT version_num FROM alembic_version LIMIT 1")
            ).scalar_one_or_none()
        checks["database"] = {"ok": True}
        checks["migrations"] = {"ok": version is not None, "revision": version}
        ok = ok and version is not None
    except Exception as exc:
        log.warning("readiness.database_failed", error=type(exc).__name__)
        checks["database"] = {"ok": False, "error": type(exc).__name__}
        ok = False

    target = settings.data_dir if settings.data_dir.exists() else settings.data_dir.anchor or "/"
    free = shutil.disk_usage(target).free
    disk_ok = free >= settings.min_free_disk_bytes
    checks["disk"] = {"ok": disk_ok, "free_bytes": free}
    return ok and disk_ok, checks


@router.get("/readyz")
def readyz(request: Request) -> JSONResponse:
    ready, checks = readiness(request.app.state.db, request.app.state.core_settings)
    return JSONResponse(
        {"status": "ok" if ready else "fail", "checks": checks}, status_code=200 if ready else 503
    )
