"""Customer Support Agent: support.conversation (24-hour demo state) and support.evaluation_run.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANT_APP_ROLE = """
DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'reluai_app') THEN
    GRANT USAGE ON SCHEMA support TO reluai_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA support TO reluai_app;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA support TO reluai_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA support
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO reluai_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA support GRANT USAGE, SELECT ON SEQUENCES TO reluai_app;
  END IF;
END $$;
"""

JSON = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS support")
    op.create_table(
        "conversation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("visitor_key", sa.String(length=16), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=False),
        sa.Column("scenario_id", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("turns", sa.Integer(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("providers", JSON, nullable=False),
        sa.Column("state", JSON, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversation")),
        schema="support",
    )  # fmt: skip
    op.create_index("ix_conversation_updated_at", "conversation", ["updated_at"], schema="support")
    op.create_table(
        "evaluation_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "ran_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("scenarios", sa.Integer(), nullable=False),
        sa.Column("passed", sa.Integer(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("median_latency_ms", sa.Integer(), nullable=False),
        sa.Column("p95_latency_ms", sa.Integer(), nullable=False),
        sa.Column("providers", JSON, nullable=False),
        sa.Column("by_category", JSON, nullable=False),
        sa.Column("environment", JSON, nullable=False),
        sa.Column("results", JSON, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_run")),
        schema="support",
    )
    op.create_index(
        "ix_support_evaluation_label_ran_at",
        "evaluation_run",
        ["label", "ran_at"],
        schema="support",
    )
    op.execute(GRANT_APP_ROLE)


def downgrade() -> None:
    op.drop_index(
        "ix_support_evaluation_label_ran_at", table_name="evaluation_run", schema="support"
    )
    op.drop_table("evaluation_run", schema="support")
    op.drop_index("ix_conversation_updated_at", table_name="conversation", schema="support")
    op.drop_table("conversation", schema="support")
    op.execute("DROP SCHEMA IF EXISTS support")
