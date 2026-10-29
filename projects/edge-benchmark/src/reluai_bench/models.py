"""Database schema ``bench``: benchmark runs (one row per run of the whole suite)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reluai_core.db import Base

SCHEMA = "bench"


class BenchmarkRun(Base):
    __tablename__ = "run"
    __table_args__ = (
        Index("ix_bench_run_ran_at", "ran_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    label: Mapped[str] = mapped_column(String(20))  # scheduled | manual
    duration_seconds: Mapped[float] = mapped_column(Float)
    hardware_id: Mapped[str] = mapped_column(String(16))
    hardware: Mapped[dict[str, Any]] = mapped_column(JSONB)
    protocol: Mapped[dict[str, Any]] = mapped_column(JSONB)
    build: Mapped[dict[str, Any]] = mapped_column(JSONB)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    agreement: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
