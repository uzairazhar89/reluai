"""Database schema ``retrieval``: documents and their chunks with a full-text index.

``chunk.tsv`` is a stored generated column: the heading path is weighted ``A`` and the
chunk text ``B``, so a passage under a matching heading ranks above a passing mention.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from reluai_core.db import Base

SCHEMA = "retrieval"
TSV_EXPRESSION = (
    "setweight(to_tsvector('english', coalesce(heading, '')), 'A') || "
    "setweight(to_tsvector('english', text), 'B')"
)


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (
        UniqueConstraint("collection", "external_id", name="uq_document_collection_external"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    collection: Mapped[str] = mapped_column(String(40), index=True)
    external_id: Mapped[str] = mapped_column(String(120))
    title: Mapped[str] = mapped_column(String(300))
    source: Mapped[str] = mapped_column(String(300))  # shown in citations
    url: Mapped[str | None] = mapped_column(String(500))
    synthetic: Mapped[bool] = mapped_column(Boolean)
    content_sha256: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Chunk(Base):
    __tablename__ = "chunk"
    __table_args__ = (
        Index("ix_chunk_tsv", "tsv", postgresql_using="gin"),
        Index("ix_chunk_document_ordinal", "document_id", "ordinal", unique=True),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey(f"{SCHEMA}.document.id", ondelete="CASCADE")
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(300))
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int] = mapped_column(Integer)
    char_end: Mapped[int] = mapped_column(Integer)
    words: Mapped[int] = mapped_column(Integer)
    tsv: Mapped[Any] = mapped_column(TSVECTOR, Computed(TSV_EXPRESSION, persisted=True))
