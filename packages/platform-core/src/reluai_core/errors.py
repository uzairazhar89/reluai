"""RFC 9457 problem-details responses. Clients never see stack traces or internal messages."""

from __future__ import annotations

from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from reluai_core.logging import get_logger

PROBLEM_JSON = "application/problem+json"
log = get_logger(__name__)


class ProblemError(Exception):
    """Raise from application code to return a specific problem response."""

    def __init__(
        self,
        status: int,
        detail: str,
        *,
        code: str | None = None,
        headers: dict[str, str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.code = code
        self.headers = headers or {}
        self.extra = extra or {}


def problem_response(
    status: int,
    detail: str,
    *,
    code: str | None = None,
    instance: str | None = None,
    headers: dict[str, str] | None = None,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
    }
    if code:
        body["code"] = code
    if instance:
        body["instance"] = instance
    request_id = structlog.contextvars.get_contextvars().get("request_id")
    if request_id:
        body["request_id"] = request_id
    if extra:
        body.update(extra)
    return JSONResponse(body, status_code=status, media_type=PROBLEM_JSON, headers=headers)


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def _problem(request: Request, exc: ProblemError) -> JSONResponse:
        return problem_response(
            exc.status,
            exc.detail,
            code=exc.code,
            instance=request.url.path,
            headers=exc.headers,
            extra=exc.extra,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
        return problem_response(
            exc.status_code, detail, instance=request.url.path, headers=dict(exc.headers or {})
        )

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return problem_response(
            422,
            "Request validation failed",
            code="validation_error",
            instance=request.url.path,
            extra={"errors": errors},
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.error("request.unhandled_error", path=request.url.path, exc_info=exc)
        return problem_response(
            500,
            "An internal error occurred. It has been logged.",
            code="internal_error",
            instance=request.url.path,
        )
