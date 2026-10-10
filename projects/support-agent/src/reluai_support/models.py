"""Database schema ``support``: demo conversations (deleted after a day) and evaluations."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reluai_core.db import Base

SUPPORT = {"schema": "support"}


class Conversation(Base):
    """One demo conversation. ``state`` is the full ``SessionState`` as JSON."""

    __tablename__ = "conversation"
    __table_args__ = (Index("ix_conversation_updated_at", "updated_at"), SUPPORT)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    visitor_key: Mapped[str] = mapped_column(String(16))
    customer_id: Mapped[int] = mapped_column(BigInteger)
    scenario_id: Mapped[str | None] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20))
    turns: Mapped[int] = mapped_column(Integer)
    tokens: Mapped[int] = mapped_column(Integer)
    providers: Mapped[list[str]] = mapped_column(JSONB)
    state: Mapped[dict[str, Any]] = mapped_column(JSONB)


class EvaluationRun(Base):
    """One run of the scenario suite against one provider chain."""

    __tablename__ = "evaluation_run"
    __table_args__ = (Index("ix_support_evaluation_label_ran_at", "label", "ran_at"), SUPPORT)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    label: Mapped[str] = mapped_column(String(80))
    scenarios: Mapped[int] = mapped_column(Integer)
    passed: Mapped[int] = mapped_column(Integer)
    tokens: Mapped[int] = mapped_column(Integer)
    median_latency_ms: Mapped[int] = mapped_column(Integer)
    p95_latency_ms: Mapped[int] = mapped_column(Integer)
    providers: Mapped[list[str]] = mapped_column(JSONB)
    by_category: Mapped[dict[str, Any]] = mapped_column(JSONB)
    environment: Mapped[dict[str, Any]] = mapped_column(JSONB)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
