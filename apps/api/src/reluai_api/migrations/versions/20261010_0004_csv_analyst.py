"""AI CSV Analyst: csv.query_log (outcomes only, no question text) and csv.evaluation_run.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANT_APP_ROLE = """
DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'reluai_app') THEN
    GRANT USAGE ON SCHEMA csv TO reluai_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA csv TO reluai_app;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA csv TO reluai_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA csv
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO reluai_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA csv GRANT USAGE, SELECT ON SEQUENCES TO reluai_app;
  END IF;
END $$;
"""


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS csv")
    op.create_table(
        "query_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("dataset_kind", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("interpreter", sa.String(length=8), nullable=False),
        sa.Column("pattern", sa.String(length=40), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("retries", sa.Integer(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("result_rows", sa.Integer(), nullable=False),
        sa.Column("interpret_ms", sa.Float(), nullable=False),
        sa.Column("query_ms", sa.Float(), nullable=False),
        sa.Column("error_code", sa.String(length=40), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_query_log")),
        schema="csv",
    )
    op.create_index("ix_query_log_ts", "query_log", ["ts"], unique=False, schema="csv")
    op.create_table(
        "evaluation_run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "ran_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("questions", sa.Integer(), nullable=False),
        sa.Column("correct", sa.Integer(), nullable=False),
        sa.Column("wrong", sa.Integer(), nullable=False),
        sa.Column("declined_expected", sa.Integer(), nullable=False),
        sa.Column("declined_unexpected", sa.Integer(), nullable=False),
        sa.Column("held_out", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("query_p50_ms", sa.Float(), nullable=False),
        sa.Column("query_p95_ms", sa.Float(), nullable=False),
        sa.Column("environment", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("items", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_run")),
        schema="csv",
    )
    op.create_index(
        "ix_evaluation_run_ran_at", "evaluation_run", ["ran_at"], unique=False, schema="csv"
    )
    op.execute(GRANT_APP_ROLE)


def downgrade() -> None:
    op.drop_index("ix_evaluation_run_ran_at", table_name="evaluation_run", schema="csv")
    op.drop_table("evaluation_run", schema="csv")
    op.drop_index("ix_query_log_ts", table_name="query_log", schema="csv")
    op.drop_table("query_log", schema="csv")
    op.execute("DROP SCHEMA IF EXISTS csv")
