"""Request and response models of the CSV Analyst API (they become the website's types)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from reluai_csv.plan import Chart, QueryPlan

Status = Literal["answered", "not_understood", "refused", "failed"]


class ValueCount(BaseModel):
    value: str
    count: int


class ColumnOut(BaseModel):
    name: str
    kind: str
    sql_type: str
    description: str
    non_null: int
    nulls: int
    distinct: int
    min: str | None
    max: str | None
    mean: float | None
    top_values: list[ValueCount]


class FindingOut(BaseModel):
    severity: Literal["warning", "info"]
    code: str
    message: str
    column: str | None
    count: int | None


class DatasetOut(BaseModel):
    id: str
    kind: Literal["bundled", "upload"]
    title: str
    table: str
    rows: int
    duplicate_rows: int
    columns: list[ColumnOut]
    findings: list[FindingOut]
    provenance: str
    examples: list[str]
    expires_at: datetime | None = None
    llm_available: bool = Field(
        default=False,
        description="Whether a language model is configured to read questions the rules cannot",
    )


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dataset: str = Field(pattern=r"^(retail|[0-9a-f]{32})$", description="'retail' or an upload id")
    question: str = Field(min_length=3, max_length=300)
    allow_llm: bool = Field(
        default=False,
        description=(
            "Uploads only: allow sending the column names and types (never the rows) to an "
            "LLM provider if the rules cannot interpret the question."
        ),
    )


class AttemptOut(BaseModel):
    provider: str
    model: str
    outcome: str
    latency_ms: int


class InterpreterOut(BaseModel):
    kind: Literal["rules", "llm", "none"]
    pattern: str | None = None
    provider: str | None = None
    model: str | None = None
    retries: int = 0
    tokens: int = 0
    latency_ms: int = 0
    attempts: list[AttemptOut] = Field(default_factory=list)


class ResultColumn(BaseModel):
    name: str
    role: Literal["time", "group", "metric"]
    kind: str
    label: str = Field(description="Heading for the column, e.g. 'Total revenue'")


class Timings(BaseModel):
    interpret_ms: float
    query_ms: float
    total_ms: float


class AskResponse(BaseModel):
    status: Status
    question: str
    message: str | None = None
    interpreter: InterpreterOut
    plan: QueryPlan | None = None
    summary: str | None = None
    sql: str | None = None
    pandas: str | None = None
    columns: list[ResultColumn] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    truncated: bool = False
    chart: Chart | None = None
    timings: Timings
    suggestions: list[str] = Field(default_factory=list)
    issues: list[str] = Field(default_factory=list)


class EvaluationSet(BaseModel):
    questions: int
    correct: int
    wrong: int
    declined_expected: int
    declined_unexpected: int
    accuracy: float = Field(description="Correct plans among questions the rules should answer")


class EvaluationItem(BaseModel):
    set: Literal["development", "held_out"]
    question: str
    expected: Literal["answer", "decline"]
    outcome: Literal["correct", "wrong", "declined", "answered_unexpectedly", "declined_correctly"]
    pattern: str | None
    summary: str | None
    query_ms: float | None


class EvaluationOut(BaseModel):
    ran_at: datetime
    development: EvaluationSet
    held_out: EvaluationSet
    query_p50_ms: float
    query_p95_ms: float
    environment: dict[str, Any]
    items: list[EvaluationItem]


class UsageOut(BaseModel):
    """Last 30 days of visitor questions, from the outcome log."""

    questions: int
    answered_by_rules: int
    answered_by_llm: int
    not_understood: int
    refused: int
    llm_retries: int
