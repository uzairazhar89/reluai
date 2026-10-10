"""A conversation's full state, serialisable to JSON so it can pause for approval.

``messages`` is exactly what the model sees (system prompt, customer turns, tool calls and
results). Everything else is the record the page shows and the evaluation checks: the
visible transcript, the trace of every step, and the simulated tickets, approvals and
refunds the tools created.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from reluai_inference.types import Message

Status = Literal["active", "awaiting_approval", "closed"]


def now() -> datetime:
    return datetime.now(UTC)


class TranscriptEntry(BaseModel):
    role: Literal["customer", "agent", "supervisor"]
    text: str
    at: datetime = Field(default_factory=now)
    citations: list[int] = Field(default_factory=list)


class Step(BaseModel):
    """One entry in the trace: a model call, a tool call, or a supervisor decision."""

    seq: int
    turn: int
    kind: Literal["model", "tool", "approval"]
    name: str
    provider: str | None = None
    model: str | None = None
    arguments: dict[str, Any] | None = None
    result: Any = None
    ok: bool = True
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    note: str | None = None


class Source(BaseModel):
    """A policy passage the agent retrieved; its position + 1 is its citation number."""

    chunk_id: int
    heading: str
    text: str
    quote: str


class Ticket(BaseModel):
    id: str
    category: str
    priority: str
    invoice_no: str | None
    summary: str
    created_at: datetime = Field(default_factory=now)


class ApprovalRequest(BaseModel):
    id: str
    invoice_no: str
    reason: str
    amount: float
    status: Literal["pending", "approved", "rejected"]
    decided_by: Literal["agent", "supervisor"] | None = None
    note: str | None = None
    requested_at: datetime = Field(default_factory=now)
    decided_at: datetime | None = None


class Refund(BaseModel):
    """A simulated refund: recorded, never paid."""

    invoice_no: str
    reason: str
    amount: float
    approved_by: Literal["agent", "supervisor"]
    at: datetime = Field(default_factory=now)


class SessionState(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    customer_id: int
    scenario_id: str | None = None
    status: Status = "active"
    turn: int = 0
    messages: list[Message] = Field(default_factory=list)
    transcript: list[TranscriptEntry] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    sources: list[Source] = Field(default_factory=list)
    calculations: dict[str, dict[str, Any]] = Field(default_factory=dict)
    approvals: list[ApprovalRequest] = Field(default_factory=list)
    refunds: list[Refund] = Field(default_factory=list)
    tickets: list[Ticket] = Field(default_factory=list)
    reply: str | None = None
    providers: list[str] = Field(default_factory=list)
    tokens: int = 0

    def add_step(self, **fields: Any) -> Step:
        step = Step(seq=len(self.steps) + 1, turn=self.turn, **fields)
        self.steps.append(step)
        return step

    @property
    def pending_approval(self) -> ApprovalRequest | None:
        return next((a for a in self.approvals if a.status == "pending"), None)
