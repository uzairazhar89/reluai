"""Job queue tables (procrastinate), installed from the pinned library's own schema file.

Upgrading procrastinate requires a new migration that applies its migration scripts
(see procrastinate's ``sql/migrations`` directory for the versions in between).

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
from procrastinate.schema import SchemaManager

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANT_APP_ROLE = """
DO $$ BEGIN
  IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'reluai_app') THEN
    GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO reluai_app;
    GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO reluai_app;
  END IF;
END $$;
"""


def upgrade() -> None:
    bind = op.get_bind()
    exists = bind.exec_driver_sql("SELECT to_regclass('public.procrastinate_jobs')").scalar()
    if exists is None:
        # The schema file has many statements; run it through the driver directly so it is
        # sent as one simple query (no parameter parsing of its PL/pgSQL bodies).
        driver_conn = bind.connection.driver_connection
        driver_conn.execute(SchemaManager.get_schema())  # type: ignore[union-attr]
    op.execute(GRANT_APP_ROLE)


def downgrade() -> None:
    raise NotImplementedError(
        "Dropping the job queue would discard queued jobs; restore a backup instead."
    )
