"""API response and request models (the public contract consumed by the website)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class RunOut(_Out):
    id: uuid.UUID
    scenario: str
    trigger: str
    simulated: bool
    status: Literal["queued", "running", "succeeded", "failed"]
    drop_key: str | None
    queued_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    rows_read: int
    rows_accepted: int
    rows_rejected: int
    rows_deduplicated: int
    rows_warned: int
    rows_inserted: int
    rows_unchanged: int
    source_retries: int
    dq_score: float | None
    failure_step: str | None
    error_message: str | None
    note: str | None


class StepOut(_Out):
    position: int
    name: str
    status: str
    started_at: datetime
    duration_ms: int
    rows_in: int | None
    rows_out: int | None
    detail: dict[str, Any] | None


class LogOut(_Out):
    ts: datetime
    level: str
    event: str
    fields: dict[str, Any]


class DqOut(_Out):
    check_name: str
    dimension: str
    stage: str
    severity: str
    passed: bool
    observed: float | None
    threshold: str
    weight: float
    detail: str


class ReasonCount(BaseModel):
    code: str
    label: str
    severity: str
    explanation: str
    count: int


class RunDetailOut(BaseModel):
    run: RunOut
    steps: list[StepOut]
    checks: list[DqOut]
    reasons: list[ReasonCount]
    warnings: list[ReasonCount]
    logs: list[LogOut]
    environment: dict[str, Any] | None
    dq_formula: str = "100 × Σ(weight × passed) / Σ(weight); weights: gate 3, warn 2, info 1"


class QuarantineRowOut(_Out):
    line_number: int
    reason_code: str
    severity: str
    raw: dict[str, Any]


class QuarantinePage(BaseModel):
    total: int
    items: list[QuarantineRowOut]


class WarehouseStats(BaseModel):
    invoice_lines: int
    invoices: int
    customers: int
    products: int
    net_revenue_gbp: float


class TrendPoint(BaseModel):
    id: uuid.UUID
    started_at: datetime | None
    status: str
    scenario: str
    drop_key: str | None
    dq_score: float | None
    duration_ms: int | None
    rows_read: int
    rows_rejected: int


class SummaryOut(BaseModel):
    last_run: RunOut | None
    last_success: RunOut | None
    runs_total: int
    failures_recent: int
    recent_window: int
    drops_loaded: int
    drops_total: int
    warehouse: WarehouseStats
    pending_runs: int
    lease_holder: str | None
    trend: list[TrendPoint]


class ScenarioOut(BaseModel):
    id: str
    title: str
    description: str
    simulated: bool
    expected: str


class DropOut(BaseModel):
    key: str
    rows: int
    loaded: bool
    first_loaded_at: datetime | None
    times_processed: int


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: str = Field(pattern=r"^[a-z_]{3,32}$")


class RunAccepted(BaseModel):
    run_id: uuid.UUID
    status: str
    pending_runs: int


class DropResult(BaseModel):
    drop_key: str
    run_id: uuid.UUID
    finished_at: datetime | None
    rows_read: int
    rows_rejected: int
    rows_deduplicated: int
    rows_published: int
    dq_score: float | None
    duration_ms: int | None


class DurationStats(BaseModel):
    median_ms: int | None
    p95_ms: int | None
    max_ms: int | None


class ResultsTotals(BaseModel):
    drops: int
    rows_read: int
    rows_rejected: int
    rows_deduplicated: int
    rows_published: int


class ResultsOut(BaseModel):
    """Measured results: the latest successful run of every loaded drop."""

    drops: list[DropResult]
    totals: ResultsTotals
    duration: DurationStats
    environment: dict[str, Any] | None
    runs_succeeded: int
    runs_failed: int
