"""ASGI middleware: request IDs, access logging, metrics and request-body limits."""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Mapping

import orjson
import structlog
from starlette.datastructures import Headers
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from reluai_core.logging import get_logger
from reluai_core.metrics import HTTP_LATENCY, HTTP_REQUESTS

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
log = get_logger("reluai.access")


def client_ip(request: Request) -> str:
    """Client address as seen by the edge proxy.

    In every deployment the API is reachable only through nginx on an internal network, and
    nginx overwrites ``X-Real-IP``; outside that setup we fall back to the socket peer.
    """
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


class RequestContextMiddleware:
    """Assigns a request ID, binds it to the log context, records metrics and an access line."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        incoming = headers.get("x-request-id", "")
        request_id = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        status_code = 500
        response_started = False
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code, response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_code = message["status"]
                raw = list(message.get("headers", []))
                raw.append((b"x-request-id", request_id.encode()))
                message["headers"] = raw
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            # Render unhandled errors here (inside the request context) so the problem
            # response carries the request ID; details stay in the log only.
            log.exception("request.unhandled_error", path=scope.get("path", ""))
            if response_started:
                raise
            body = orjson.dumps(
                {
                    "type": "about:blank",
                    "title": "Internal Server Error",
                    "status": 500,
                    "detail": "An internal error occurred. It has been logged.",
                    "code": "internal_error",
                    "request_id": request_id,
                }
            )
            await send_wrapper(
                {
                    "type": "http.response.start",
                    "status": 500,
                    "headers": [
                        (b"content-type", b"application/problem+json"),
                        (b"content-length", str(len(body)).encode()),
                    ],
                }
            )
            await send_wrapper({"type": "http.response.body", "body": body})
        finally:
            elapsed = time.perf_counter() - started
            route = scope.get("route")
            template = getattr(route, "path", None) or "unmatched"
            method = scope.get("method", "GET")
            HTTP_REQUESTS.labels(method=method, route=template, status=str(status_code)).inc()
            HTTP_LATENCY.labels(method=method, route=template).observe(elapsed)
            if template not in {"/healthz", "/metrics"}:
                log.info(
                    "request.completed",
                    method=method,
                    path=scope.get("path", ""),
                    route=template,
                    status=status_code,
                    duration_ms=round(elapsed * 1000, 1),
                    client_ip=headers.get("x-real-ip")
                    or (scope.get("client") or ("unknown", 0))[0],
                )
            structlog.contextvars.clear_contextvars()


class BodySizeLimitMiddleware:
    """Rejects request bodies over a per-path-prefix limit with 413, without buffering them.

    nginx enforces the same limits at the edge; this is defence in depth for direct access
    (staging, tests) and for chunked uploads that omit Content-Length.
    """

    def __init__(
        self, app: ASGIApp, *, default_limit: int, prefix_limits: Mapping[str, int] | None = None
    ) -> None:
        self.app = app
        self.default_limit = default_limit
        # Longest prefix wins.
        self.prefix_limits = sorted((prefix_limits or {}).items(), key=lambda kv: -len(kv[0]))

    def limit_for(self, path: str) -> int:
        for prefix, limit in self.prefix_limits:
            if path.startswith(prefix):
                return limit
        return self.default_limit

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = self.limit_for(scope.get("path", ""))
        declared = Headers(scope=scope).get("content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await self._reject(send, limit)
            return

        received = 0
        response_started = False

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _BodyTooLargeError()
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except _BodyTooLargeError:
            if not response_started:
                await self._reject(send, limit)

    @staticmethod
    async def _reject(send: Send, limit: int) -> None:
        body = orjson.dumps(
            {
                "type": "about:blank",
                "title": "Content Too Large",
                "status": 413,
                "detail": f"Request body exceeds the {limit} byte limit for this endpoint.",
                "code": "body_too_large",
            }
        )
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class _BodyTooLargeError(StarletteHTTPException):
    """Subclasses HTTPException so FastAPI's body parser re-raises it instead of turning it
    into a generic 400; the problem handler then renders a 413."""

    def __init__(self) -> None:
        super().__init__(
            status_code=413, detail="Request body exceeds the limit for this endpoint."
        )
