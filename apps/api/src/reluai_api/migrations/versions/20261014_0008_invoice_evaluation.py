"""Document Intelligence: docs.invoice_evaluation_run (invoice extraction accuracy).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-14
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = postgresql.JSONB(astext_type=sa.Text())

GRANT_APP_ROLE = """
DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'reluai_app') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON docs.invoice_evaluation_run TO reluai_app;
  END IF;
END $$;
"""


def upgrade() -> None:
    op.create_table(
        "invoice_evaluation_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ran_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("documents", sa.Integer(), nullable=False),
        sa.Column("exact", sa.Integer(), nullable=False),
        sa.Column("median_ms", sa.Integer(), nullable=False),
        sa.Column("metrics", JSON, nullable=False),
        sa.Column("environment", JSON, nullable=False),
        sa.Column("results", JSON, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_evaluation_run")),
        schema="docs",
    )  # fmt: skip
    op.create_index(
        "ix_docs_invoice_evaluation_ran_at", "invoice_evaluation_run", ["ran_at"], schema="docs"
    )
    op.execute(GRANT_APP_ROLE)


def downgrade() -> None:
    op.drop_index(
        "ix_docs_invoice_evaluation_ran_at", table_name="invoice_evaluation_run", schema="docs"
    )
    op.drop_table("invoice_evaluation_run", schema="docs")
