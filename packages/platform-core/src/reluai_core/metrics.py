"""Prometheus metrics. Supports multi-process servers via PROMETHEUS_MULTIPROC_DIR."""

from __future__ import annotations

import os

from fastapi import APIRouter, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)

HTTP_REQUESTS = Counter(
    "reluai_http_requests_total", "HTTP requests", ["method", "route", "status"]
)
HTTP_LATENCY = Histogram(
    "reluai_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "route"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
JOBS_DEFERRED = Counter("reluai_jobs_deferred_total", "Background jobs queued", ["task"])
JOBS_REJECTED = Counter(
    "reluai_jobs_rejected_total", "Background jobs refused because the queue was full", ["task"]
)
QUEUE_DEPTH = Gauge(
    "reluai_queue_depth", "Jobs waiting or running", ["queue"], multiprocess_mode="max"
)

router = APIRouter(include_in_schema=False)


@router.get("/metrics")
def metrics() -> Response:
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)  # type: ignore[no-untyped-call]
        data = generate_latest(registry)
    else:
        data = generate_latest()
    return Response(content=data, media_type=CONTENT_TYPE_LATEST)
