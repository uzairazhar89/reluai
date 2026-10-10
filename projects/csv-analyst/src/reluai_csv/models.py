"""Database schema ``csv``: an outcome log (no question text) and evaluation runs."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Float, Index, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reluai_core.db import Base

CSV = {"schema": "csv"}


class QueryLog(Base):
    """One row per question. Questions themselves are not stored, only how they went."""

    __tablename__ = "query_log"
    __table_args__ = (Index("ix_query_log_ts", "ts"), CSV)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    dataset_kind: Mapped[str] = mapped_column(String(8))  # bundled | upload
    status: Mapped[str] = mapped_column(String(16))  # answered | not_understood | refused | failed
    interpreter: Mapped[str] = mapped_column(String(8))  # rules | llm | none
    pattern: Mapped[str | None] = mapped_column(String(40))
    provider: Mapped[str | None] = mapped_column(String(32))
    retries: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    result_rows: Mapped[int] = mapped_column(Integer, default=0)
    interpret_ms: Mapped[float] = mapped_column(Float, default=0)
    query_ms: Mapped[float] = mapped_column(Float, default=0)
    error_code: Mapped[str | None] = mapped_column(String(40))


class EvaluationRun(Base):
    """A run of the fixed question sets against the bundled table.

    The columns hold the development set (written alongside the rules); ``held_out`` holds
    the set written afterwards and never tuned on."""

    __tablename__ = "evaluation_run"
    __table_args__ = (Index("ix_evaluation_run_ran_at", "ran_at"), CSV)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    questions: Mapped[int] = mapped_column(Integer)
    correct: Mapped[int] = mapped_column(Integer)
    wrong: Mapped[int] = mapped_column(Integer)
    declined_expected: Mapped[int] = mapped_column(Integer)
    declined_unexpected: Mapped[int] = mapped_column(Integer)
    held_out: Mapped[dict[str, Any]] = mapped_column(JSONB)
    query_p50_ms: Mapped[float] = mapped_column(Float)
    query_p95_ms: Mapped[float] = mapped_column(Float)
    environment: Mapped[dict[str, Any]] = mapped_column(JSONB)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
