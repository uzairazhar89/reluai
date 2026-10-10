"""API models for the support agent (these become the website's types)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScenarioOut(BaseModel):
    id: str
    title: str
    category: str
    customer_id: int
    message: str
    needs_supervisor: bool = Field(
        description="Whether the scenario involves a supervisor decision"
    )


class InvoiceSummary(BaseModel):
    invoice_no: str
    date: date
    total_gbp: float
    is_credit_note: bool


class CustomerOut(BaseModel):
    customer_id: int
    country: str
    invoices: int
    first_order: date
    last_order: date
    recent: list[InvoiceSummary]


class CatalogueOut(BaseModel):
    as_of: date
    auto_approve_limit_gbp: float
    scenarios: list[ScenarioOut]
    customers: list[CustomerOut]
    llm_available: bool


class StartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario_id: str | None = Field(default=None, max_length=40)
    customer_id: int | None = Field(default=None, ge=1)
    message: str | None = Field(default=None, min_length=3, max_length=600)

    @model_validator(mode="after")
    def _one_of(self) -> StartRequest:
        if self.scenario_id is None and (self.customer_id is None or self.message is None):
            raise ValueError("give a scenario_id, or a customer_id and a message")
        return self


class MessageRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=600)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=300)


class TranscriptOut(BaseModel):
    role: Literal["customer", "agent", "supervisor"]
    text: str
    at: datetime
    citations: list[int]


class StepOut(BaseModel):
    seq: int
    turn: int
    kind: Literal["model", "tool", "approval"]
    name: str
    provider: str | None
    model: str | None
    arguments: dict[str, Any] | None
    result: Any
    ok: bool
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    note: str | None


class SourceOut(BaseModel):
    number: int
    heading: str
    quote: str


class ApprovalOut(BaseModel):
    id: str
    invoice_no: str
    reason: str
    amount_gbp: float
    status: Literal["pending", "approved", "rejected"]
    decided_by: Literal["agent", "supervisor"] | None
    note: str | None


class RefundOut(BaseModel):
    invoice_no: str
    reason: str
    amount_gbp: float
    approved_by: Literal["agent", "supervisor"]


class TicketOut(BaseModel):
    id: str
    category: str
    priority: str
    invoice_no: str | None
    summary: str


class ConversationOut(BaseModel):
    id: uuid.UUID
    customer_id: int
    scenario_id: str | None
    status: Literal["active", "awaiting_approval", "closed"]
    turn: int
    can_reply: bool
    transcript: list[TranscriptOut]
    steps: list[StepOut]
    sources: list[SourceOut]
    approvals: list[ApprovalOut]
    refunds: list[RefundOut]
    tickets: list[TicketOut]
    providers: list[str]
    tokens: int


class EvaluationResultOut(BaseModel):
    id: str
    title: str
    category: str
    passed: bool
    failures: list[str]
    steps: int
    tool_calls: int
    tool_errors: int
    tokens: int
    latency_ms: int


class EvaluationRunOut(BaseModel):
    label: str
    ran_at: datetime
    scenarios: int
    passed: int
    tokens: int
    median_latency_ms: int
    p95_latency_ms: int
    providers: list[str]
    by_category: dict[str, list[int]]
    environment: dict[str, Any]
    results: list[EvaluationResultOut]


class PolicySectionOut(BaseModel):
    heading: str
    text: str
