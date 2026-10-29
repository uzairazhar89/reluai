"""Edge AI Benchmark Lab: schema ``bench`` with bench.run (one row per benchmark run).

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JSON = postgresql.JSONB(astext_type=sa.Text())

GRANT_APP_ROLE = """
DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'reluai_app') THEN
    GRANT USAGE ON SCHEMA bench TO reluai_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON bench.run TO reluai_app;
  END IF;
END $$;
"""


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS bench")
    op.create_table(
        "run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ran_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
                  nullable=False),
        sa.Column("label", sa.String(length=20), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("hardware_id", sa.String(length=16), nullable=False),
        sa.Column("hardware", JSON, nullable=False),
        sa.Column("protocol", JSON, nullable=False),
        sa.Column("build", JSON, nullable=False),
        sa.Column("results", JSON, nullable=False),
        sa.Column("agreement", JSON, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run")),
        schema="bench",
    )  # fmt: skip
    op.create_index("ix_bench_run_ran_at", "run", ["ran_at"], schema="bench")
    op.execute(GRANT_APP_ROLE)


def downgrade() -> None:
    op.drop_index("ix_bench_run_ran_at", table_name="run", schema="bench")
    op.drop_table("run", schema="bench")
    op.execute("DROP SCHEMA IF EXISTS bench")
