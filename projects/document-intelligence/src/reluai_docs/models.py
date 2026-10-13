"""Database schema ``docs``: uploaded and bundled documents, and evaluation runs.

A document's text and passages live in ``retrieval.document`` / ``retrieval.chunk`` under
the collection ``docs-<id>``; this table holds what the website shows about processing.
Uploads expire (``expires_at``) and are deleted with their passages by a periodic job.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from reluai_core.db import Base

SCHEMA = "docs"


def collection_for(document_id: uuid.UUID) -> str:
    return f"docs-{document_id.hex}"


class DocumentRecord(Base):
    __tablename__ = "document"
    __table_args__ = (
        Index("ix_docs_document_expires_at", "expires_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    kind: Mapped[str] = mapped_column(String(10))  # upload | sample
    visitor_key: Mapped[str | None] = mapped_column(String(16))
    filename: Mapped[str] = mapped_column(String(160))
    file_bytes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))  # queued | reading | ocr | indexing | ...
    progress_done: Mapped[int] = mapped_column(Integer, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, default=0)
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    pages_read: Mapped[int] = mapped_column(Integer, default=0)
    pages_text: Mapped[int] = mapped_column(Integer, default=0)
    pages_ocr: Mapped[int] = mapped_column(Integer, default=0)
    pages_empty: Mapped[int] = mapped_column(Integer, default=0)
    ocr_skipped: Mapped[list[int]] = mapped_column(JSONB, default=list)
    chars: Mapped[int] = mapped_column(Integer, default=0)
    chunks: Mapped[int] = mapped_column(Integer, default=0)
    truncated: Mapped[bool] = mapped_column(Boolean, default=False)
    search_mode: Mapped[str | None] = mapped_column(String(10))  # hybrid | keyword
    embedding_model: Mapped[str | None] = mapped_column(String(80))
    title: Mapped[str | None] = mapped_column(String(200))
    outline: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    page_starts: Mapped[list[int]] = mapped_column(JSONB, default=list)
    retrieval_document_id: Mapped[int | None] = mapped_column(BigInteger)
    error_code: Mapped[str | None] = mapped_column(String(30))
    error_message: Mapped[str | None] = mapped_column(String(300))
    timings: Mapped[dict[str, int]] = mapped_column(JSONB, default=dict)


class EvaluationRun(Base):
    __tablename__ = "evaluation_run"
    __table_args__ = (
        Index("ix_docs_evaluation_label_ran_at", "label", "ran_at"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    ran_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    label: Mapped[str] = mapped_column(String(80))
    document: Mapped[str] = mapped_column(String(120))
    questions: Mapped[int] = mapped_column(Integer)
    correct: Mapped[int] = mapped_column(Integer)
    tokens: Mapped[int] = mapped_column(Integer)
    median_latency_ms: Mapped[int] = mapped_column(Integer)
    p95_latency_ms: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB)
    environment: Mapped[dict[str, Any]] = mapped_column(JSONB)
    results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
