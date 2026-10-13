"""Document Intelligence: pgvector embeddings on retrieval.chunk; docs.document, docs.evaluation_run.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANT_APP_ROLE = """
DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'reluai_app') THEN
    GRANT USAGE ON SCHEMA docs TO reluai_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA docs TO reluai_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA docs
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO reluai_app;
  END IF;
END $$;
"""

JSON = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.add_column("chunk", sa.Column("embedding", Vector(384), nullable=True), schema="retrieval")

    op.execute("CREATE SCHEMA IF NOT EXISTS docs")
    op.create_table(
        "document",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("visitor_key", sa.String(length=16), nullable=True),
        sa.Column("filename", sa.String(length=160), nullable=False),
        sa.Column("file_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("progress_done", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("pages_read", sa.Integer(), nullable=False),
        sa.Column("pages_text", sa.Integer(), nullable=False),
        sa.Column("pages_ocr", sa.Integer(), nullable=False),
        sa.Column("pages_empty", sa.Integer(), nullable=False),
        sa.Column("ocr_skipped", JSON, nullable=False),
        sa.Column("chars", sa.Integer(), nullable=False),
        sa.Column("chunks", sa.Integer(), nullable=False),
        sa.Column("truncated", sa.Boolean(), nullable=False),
        sa.Column("search_mode", sa.String(length=10), nullable=True),
        sa.Column("embedding_model", sa.String(length=80), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("outline", JSON, nullable=False),
        sa.Column("page_starts", JSON, nullable=False),
        sa.Column("retrieval_document_id", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=30), nullable=True),
        sa.Column("error_message", sa.String(length=300), nullable=True),
        sa.Column("timings", JSON, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document")),
        schema="docs",
    )  # fmt: skip
    op.create_index("ix_docs_document_expires_at", "document", ["expires_at"], schema="docs")
    op.create_table(
        "evaluation_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ran_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("document", sa.String(length=120), nullable=False),
        sa.Column("questions", sa.Integer(), nullable=False),
        sa.Column("correct", sa.Integer(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("median_latency_ms", sa.Integer(), nullable=False),
        sa.Column("p95_latency_ms", sa.Integer(), nullable=False),
        sa.Column("metrics", JSON, nullable=False),
        sa.Column("environment", JSON, nullable=False),
        sa.Column("results", JSON, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_run")),
        schema="docs",
    )  # fmt: skip
    op.create_index(
        "ix_docs_evaluation_label_ran_at", "evaluation_run", ["label", "ran_at"], schema="docs"
    )
    op.execute(GRANT_APP_ROLE)


def downgrade() -> None:
    op.drop_index("ix_docs_evaluation_label_ran_at", table_name="evaluation_run", schema="docs")
    op.drop_table("evaluation_run", schema="docs")
    op.drop_index("ix_docs_document_expires_at", table_name="document", schema="docs")
    op.drop_table("document", schema="docs")
    op.execute("DROP SCHEMA IF EXISTS docs")
    op.drop_column("chunk", "embedding", schema="retrieval")
