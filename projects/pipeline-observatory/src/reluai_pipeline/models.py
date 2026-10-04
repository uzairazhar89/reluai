"""Database schema.

``pipeline.*`` holds operational metadata (runs, steps, logs, quarantine, data-quality
results); ``retail.*`` is the warehouse the pipeline publishes to and that later projects
(CSV analyst, RAG lab, support agent) read from.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reluai_core.db import Base

PIPELINE = {"schema": "pipeline"}
RETAIL = {"schema": "retail"}


# ------------------------------------------------------------------ operational metadata
class PipelineRun(Base):
    __tablename__ = "run"
    __table_args__ = (Index("ix_run_started_at", "started_at"), PIPELINE)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scenario: Mapped[str] = mapped_column(String(32))
    trigger: Mapped[str] = mapped_column(String(16))  # scheduled | visitor | cli | backfill
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), index=True)  # queued|running|succeeded|failed
    drop_key: Mapped[str | None] = mapped_column(String(7))
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    rows_read: Mapped[int] = mapped_column(Integer, default=0)
    rows_accepted: Mapped[int] = mapped_column(Integer, default=0)
    rows_rejected: Mapped[int] = mapped_column(Integer, default=0)
    rows_deduplicated: Mapped[int] = mapped_column(Integer, default=0)
    rows_warned: Mapped[int] = mapped_column(Integer, default=0)
    rows_inserted: Mapped[int] = mapped_column(Integer, default=0)
    rows_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    source_retries: Mapped[int] = mapped_column(Integer, default=0)
    dq_score: Mapped[float | None] = mapped_column(Float)
    failure_step: Mapped[str | None] = mapped_column(String(32))
    error_message: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    visitor_key: Mapped[str | None] = mapped_column(String(16))


class RunStep(Base):
    __tablename__ = "run_step"
    __table_args__ = PIPELINE

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline.run.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))  # succeeded | failed | skipped
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer)
    rows_in: Mapped[int | None] = mapped_column(Integer)
    rows_out: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class RunLog(Base):
    __tablename__ = "run_log"
    __table_args__ = PIPELINE

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline.run.id", ondelete="CASCADE"), index=True
    )
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    level: Mapped[str] = mapped_column(String(8))
    event: Mapped[str] = mapped_column(String(64))
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)


class QuarantinedRow(Base):
    __tablename__ = "quarantine"
    __table_args__ = (Index("ix_quarantine_run_reason", "run_id", "reason_code"), PIPELINE)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("pipeline.run.id", ondelete="CASCADE"))
    drop_key: Mapped[str] = mapped_column(String(7))
    line_number: Mapped[int] = mapped_column(Integer)
    reason_code: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(8))  # reject | dropped
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)


class DqResult(Base):
    __tablename__ = "dq_result"
    __table_args__ = PIPELINE

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("pipeline.run.id", ondelete="CASCADE"), index=True
    )
    check_name: Mapped[str] = mapped_column(String(40))
    dimension: Mapped[str] = mapped_column(String(16))
    stage: Mapped[str] = mapped_column(String(12))  # batch | warehouse
    severity: Mapped[str] = mapped_column(String(8))  # gate | warn | info
    passed: Mapped[bool] = mapped_column(Boolean)
    observed: Mapped[float | None] = mapped_column(Float)
    threshold: Mapped[str] = mapped_column(String(40))
    weight: Mapped[float] = mapped_column(Float)
    detail: Mapped[str] = mapped_column(Text)


class SourceDrop(Base):
    __tablename__ = "source_drop"
    __table_args__ = PIPELINE

    drop_key: Mapped[str] = mapped_column(String(7), primary_key=True)  # YYYY-MM
    file_name: Mapped[str] = mapped_column(String(64))
    sha256: Mapped[str] = mapped_column(String(64))
    rows: Mapped[int] = mapped_column(Integer)
    first_loaded_run_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    first_loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    times_processed: Mapped[int] = mapped_column(Integer, default=1)


# ------------------------------------------------------------------------- warehouse
class Customer(Base):
    __tablename__ = "customer"
    __table_args__ = RETAIL

    customer_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    country: Mapped[str] = mapped_column(String(64))
    first_seen: Mapped[date] = mapped_column(Date)


class Product(Base):
    __tablename__ = "product"
    __table_args__ = RETAIL

    stock_code: Mapped[str] = mapped_column(String(20), primary_key=True)
    description: Mapped[str] = mapped_column(String(200))
    line_type: Mapped[str] = mapped_column(String(16))
    first_seen: Mapped[date] = mapped_column(Date)
    last_seen: Mapped[date] = mapped_column(Date)


class Invoice(Base):
    __tablename__ = "invoice"
    __table_args__ = (Index("ix_invoice_invoiced_at", "invoiced_at"), RETAIL)

    invoice_no: Mapped[str] = mapped_column(String(8), primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(
        ForeignKey("retail.customer.customer_id"), index=True
    )
    country: Mapped[str] = mapped_column(String(64))
    invoiced_at: Mapped[datetime] = mapped_column(DateTime(timezone=False))
    kind: Mapped[str] = mapped_column(String(16))  # sale | cancellation
    drop_key: Mapped[str] = mapped_column(String(7))
    loaded_run_id: Mapped[uuid.UUID] = mapped_column(Uuid)


class InvoiceLine(Base):
    __tablename__ = "invoice_line"
    __table_args__ = RETAIL

    line_key: Mapped[str] = mapped_column(String(32), primary_key=True)
    invoice_no: Mapped[str] = mapped_column(ForeignKey("retail.invoice.invoice_no"), index=True)
    stock_code: Mapped[str] = mapped_column(ForeignKey("retail.product.stock_code"), index=True)
    description: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    line_type: Mapped[str] = mapped_column(String(16))
    drop_key: Mapped[str] = mapped_column(String(7), index=True)
    loaded_run_id: Mapped[uuid.UUID] = mapped_column(Uuid)
