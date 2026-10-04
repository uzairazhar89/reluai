"""Alembic environment: one metadata for every module, schemas platform/pipeline/retail."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine, pool

import reluai_api.contact  # noqa: F401 - registers platform.contact_message
import reluai_core.ratelimit  # noqa: F401 - registers platform.rate_counter
import reluai_inference.ledger  # noqa: F401 - registers platform.llm_usage
import reluai_pipeline.models  # noqa: F401 - registers pipeline.* and retail.*
from reluai_core.db import Base
from reluai_core.settings import CoreSettings

SCHEMAS = {"platform", "pipeline", "retail"}
config = context.config
target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: object) -> bool:
    if type_ == "schema":
        return name in SCHEMAS
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url") or CoreSettings().migration_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url") or CoreSettings().migration_url
    engine = create_engine(url, poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
