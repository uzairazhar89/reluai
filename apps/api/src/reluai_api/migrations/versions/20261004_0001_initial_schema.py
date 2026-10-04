"""Initial schema: platform (quotas, LLM ledger), pipeline (run metadata), retail (warehouse).

Revision ID: 0001
Revises:
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SCHEMAS = ("platform", "pipeline", "retail")

# Grants for the least-privilege runtime role, if the deployment created it
# (infra/postgres/init/01-app-role.sh). Local development uses a single owner role.
GRANT_APP_ROLE = """
DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'reluai_app') THEN
    GRANT USAGE ON SCHEMA platform, pipeline, retail TO reluai_app;
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA platform, pipeline, retail
      TO reluai_app;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA platform, pipeline, retail TO reluai_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA platform, pipeline, retail
      GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO reluai_app;
    ALTER DEFAULT PRIVILEGES IN SCHEMA platform, pipeline, retail
      GRANT USAGE, SELECT ON SEQUENCES TO reluai_app;
  END IF;
END $$;
"""


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
    op.create_table(
        "run",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scenario", sa.String(length=32), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("simulated", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("drop_key", sa.String(length=7), nullable=True),
        sa.Column(
            "queued_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("rows_read", sa.Integer(), nullable=False),
        sa.Column("rows_accepted", sa.Integer(), nullable=False),
        sa.Column("rows_rejected", sa.Integer(), nullable=False),
        sa.Column("rows_deduplicated", sa.Integer(), nullable=False),
        sa.Column("rows_warned", sa.Integer(), nullable=False),
        sa.Column("rows_inserted", sa.Integer(), nullable=False),
        sa.Column("rows_unchanged", sa.Integer(), nullable=False),
        sa.Column("source_retries", sa.Integer(), nullable=False),
        sa.Column("dq_score", sa.Float(), nullable=True),
        sa.Column("failure_step", sa.String(length=32), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("environment", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("visitor_key", sa.String(length=16), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run")),
        schema="pipeline",
    )
    op.create_index(
        op.f("ix_pipeline_run_status"), "run", ["status"], unique=False, schema="pipeline"
    )
    op.create_index("ix_run_started_at", "run", ["started_at"], unique=False, schema="pipeline")
    op.create_table(
        "source_drop",
        sa.Column("drop_key", sa.String(length=7), nullable=False),
        sa.Column("file_name", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("rows", sa.Integer(), nullable=False),
        sa.Column("first_loaded_run_id", sa.Uuid(), nullable=False),
        sa.Column("first_loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("times_processed", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("drop_key", name=op.f("pk_source_drop")),
        schema="pipeline",
    )
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "ts", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("feature", sa.String(length=40), nullable=False),
        sa.Column("visitor_key", sa.String(length=16), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_llm_usage")),
        schema="platform",
    )
    op.create_index(
        "ix_llm_usage_ts_provider",
        "llm_usage",
        ["ts", "provider", "model"],
        unique=False,
        schema="platform",
    )
    op.create_index(
        op.f("ix_platform_llm_usage_visitor_key"),
        "llm_usage",
        ["visitor_key"],
        unique=False,
        schema="platform",
    )
    op.create_table(
        "rate_counter",
        sa.Column("key", sa.String(length=160), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key", "window_start", name=op.f("pk_rate_counter")),
        schema="platform",
    )
    op.create_table(
        "customer",
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("country", sa.String(length=64), nullable=False),
        sa.Column("first_seen", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("customer_id", name=op.f("pk_customer")),
        schema="retail",
    )
    op.create_table(
        "product",
        sa.Column("stock_code", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("line_type", sa.String(length=16), nullable=False),
        sa.Column("first_seen", sa.Date(), nullable=False),
        sa.Column("last_seen", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("stock_code", name=op.f("pk_product")),
        schema="retail",
    )
    op.create_table(
        "dq_result",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("check_name", sa.String(length=40), nullable=False),
        sa.Column("dimension", sa.String(length=16), nullable=False),
        sa.Column("stage", sa.String(length=12), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("observed", sa.Float(), nullable=True),
        sa.Column("threshold", sa.String(length=40), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["pipeline.run.id"],
            name=op.f("fk_dq_result_run_id_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dq_result")),
        schema="pipeline",
    )
    op.create_index(
        op.f("ix_pipeline_dq_result_run_id"),
        "dq_result",
        ["run_id"],
        unique=False,
        schema="pipeline",
    )
    op.create_table(
        "quarantine",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("drop_key", sa.String(length=7), nullable=False),
        sa.Column("line_number", sa.Integer(), nullable=False),
        sa.Column("reason_code", sa.String(length=40), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["pipeline.run.id"],
            name=op.f("fk_quarantine_run_id_run"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quarantine")),
        schema="pipeline",
    )
    op.create_index(
        "ix_quarantine_run_reason",
        "quarantine",
        ["run_id", "reason_code"],
        unique=False,
        schema="pipeline",
    )
    op.create_table(
        "run_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("event", sa.String(length=64), nullable=False),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"], ["pipeline.run.id"], name=op.f("fk_run_log_run_id_run"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_log")),
        schema="pipeline",
    )
    op.create_index(
        op.f("ix_pipeline_run_log_run_id"), "run_log", ["run_id"], unique=False, schema="pipeline"
    )
    op.create_table(
        "run_step",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("rows_in", sa.Integer(), nullable=True),
        sa.Column("rows_out", sa.Integer(), nullable=True),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["pipeline.run.id"], name=op.f("fk_run_step_run_id_run"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_run_step")),
        schema="pipeline",
    )
    op.create_index(
        op.f("ix_pipeline_run_step_run_id"), "run_step", ["run_id"], unique=False, schema="pipeline"
    )
    op.create_table(
        "invoice",
        sa.Column("invoice_no", sa.String(length=8), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=True),
        sa.Column("country", sa.String(length=64), nullable=False),
        sa.Column("invoiced_at", sa.DateTime(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("drop_key", sa.String(length=7), nullable=False),
        sa.Column("loaded_run_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["retail.customer.customer_id"],
            name=op.f("fk_invoice_customer_id_customer"),
        ),
        sa.PrimaryKeyConstraint("invoice_no", name=op.f("pk_invoice")),
        schema="retail",
    )
    op.create_index(
        "ix_invoice_invoiced_at", "invoice", ["invoiced_at"], unique=False, schema="retail"
    )
    op.create_index(
        op.f("ix_retail_invoice_customer_id"),
        "invoice",
        ["customer_id"],
        unique=False,
        schema="retail",
    )
    op.create_table(
        "invoice_line",
        sa.Column("line_key", sa.String(length=32), nullable=False),
        sa.Column("invoice_no", sa.String(length=8), nullable=False),
        sa.Column("stock_code", sa.String(length=20), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("line_type", sa.String(length=16), nullable=False),
        sa.Column("drop_key", sa.String(length=7), nullable=False),
        sa.Column("loaded_run_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["invoice_no"],
            ["retail.invoice.invoice_no"],
            name=op.f("fk_invoice_line_invoice_no_invoice"),
        ),
        sa.ForeignKeyConstraint(
            ["stock_code"],
            ["retail.product.stock_code"],
            name=op.f("fk_invoice_line_stock_code_product"),
        ),
        sa.PrimaryKeyConstraint("line_key", name=op.f("pk_invoice_line")),
        schema="retail",
    )
    op.create_index(
        op.f("ix_retail_invoice_line_drop_key"),
        "invoice_line",
        ["drop_key"],
        unique=False,
        schema="retail",
    )
    op.create_index(
        op.f("ix_retail_invoice_line_invoice_no"),
        "invoice_line",
        ["invoice_no"],
        unique=False,
        schema="retail",
    )
    op.create_index(
        op.f("ix_retail_invoice_line_stock_code"),
        "invoice_line",
        ["stock_code"],
        unique=False,
        schema="retail",
    )
    op.execute(GRANT_APP_ROLE)


def downgrade() -> None:
    op.drop_index(
        op.f("ix_retail_invoice_line_stock_code"), table_name="invoice_line", schema="retail"
    )
    op.drop_index(
        op.f("ix_retail_invoice_line_invoice_no"), table_name="invoice_line", schema="retail"
    )
    op.drop_index(
        op.f("ix_retail_invoice_line_drop_key"), table_name="invoice_line", schema="retail"
    )
    op.drop_table("invoice_line", schema="retail")
    op.drop_index(op.f("ix_retail_invoice_customer_id"), table_name="invoice", schema="retail")
    op.drop_index("ix_invoice_invoiced_at", table_name="invoice", schema="retail")
    op.drop_table("invoice", schema="retail")
    op.drop_index(op.f("ix_pipeline_run_step_run_id"), table_name="run_step", schema="pipeline")
    op.drop_table("run_step", schema="pipeline")
    op.drop_index(op.f("ix_pipeline_run_log_run_id"), table_name="run_log", schema="pipeline")
    op.drop_table("run_log", schema="pipeline")
    op.drop_index("ix_quarantine_run_reason", table_name="quarantine", schema="pipeline")
    op.drop_table("quarantine", schema="pipeline")
    op.drop_index(op.f("ix_pipeline_dq_result_run_id"), table_name="dq_result", schema="pipeline")
    op.drop_table("dq_result", schema="pipeline")
    op.drop_table("product", schema="retail")
    op.drop_table("customer", schema="retail")
    op.drop_table("rate_counter", schema="platform")
    op.drop_index(
        op.f("ix_platform_llm_usage_visitor_key"), table_name="llm_usage", schema="platform"
    )
    op.drop_index("ix_llm_usage_ts_provider", table_name="llm_usage", schema="platform")
    op.drop_table("llm_usage", schema="platform")
    op.drop_table("source_drop", schema="pipeline")
    op.drop_index("ix_run_started_at", table_name="run", schema="pipeline")
    op.drop_index(op.f("ix_pipeline_run_status"), table_name="run", schema="pipeline")
    op.drop_table("run", schema="pipeline")
    for schema in reversed(SCHEMAS):
        op.execute(f"DROP SCHEMA IF EXISTS {schema}")
