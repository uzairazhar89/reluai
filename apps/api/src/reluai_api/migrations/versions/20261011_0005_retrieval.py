"""Retrieval core: retrieval.document and retrieval.chunk with a weighted full-text index.

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TSV = (
    "setweight(to_tsvector('english', coalesce(heading, '')), 'A') || "
    "setweight(to_tsvector('english', text), 'B')"
)

GRANT_APP_ROLE = """
DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'reluai_app') THEN
    GRANT USAGE ON SCHEMA retrieval TO reluai_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA retrieval TO reluai_app;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA retrieval TO reluai_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA retrieval
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO reluai_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA retrieval GRANT USAGE, SELECT ON SEQUENCES TO reluai_app;
  END IF;
END $$;
"""


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS retrieval")
    op.create_table(
        "document",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("collection", sa.String(length=40), nullable=False),
        sa.Column("external_id", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("source", sa.String(length=300), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=True),
        sa.Column("synthetic", sa.Boolean(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "indexed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document")),
        sa.UniqueConstraint("collection", "external_id", name="uq_document_collection_external"),
        schema="retrieval",
    )
    op.create_index(
        "ix_retrieval_document_collection", "document", ["collection"], schema="retrieval"
    )
    op.create_table(
        "chunk",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("document_id", sa.BigInteger(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(length=300), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("words", sa.Integer(), nullable=False),
        sa.Column("tsv", postgresql.TSVECTOR(), sa.Computed(TSV, persisted=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["retrieval.document.id"],
            name=op.f("fk_chunk_document_id_document"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chunk")),
        schema="retrieval",
    )
    op.create_index(
        "ix_chunk_tsv", "chunk", ["tsv"], unique=False, schema="retrieval", postgresql_using="gin"
    )
    op.create_index(
        "ix_chunk_document_ordinal",
        "chunk",
        ["document_id", "ordinal"],
        unique=True,
        schema="retrieval",
    )
    op.execute(GRANT_APP_ROLE)


def downgrade() -> None:
    op.drop_index("ix_chunk_document_ordinal", table_name="chunk", schema="retrieval")
    op.drop_index("ix_chunk_tsv", table_name="chunk", schema="retrieval")
    op.drop_table("chunk", schema="retrieval")
    op.drop_index("ix_retrieval_document_collection", table_name="document", schema="retrieval")
    op.drop_table("document", schema="retrieval")
    op.execute("DROP SCHEMA IF EXISTS retrieval")
