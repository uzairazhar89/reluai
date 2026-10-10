"""The migrations produce exactly the schema the models describe."""

from __future__ import annotations

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine

import reluai_api.migrations.env_models  # noqa: F401 - registers every model
from reluai_api.migrations.env_models import SCHEMAS
from reluai_core.db import Base

pytestmark = pytest.mark.db


def test_models_and_migrations_agree(database_url: str) -> None:
    def include_name(name: str | None, type_: str, parent_names: object) -> bool:
        return name in SCHEMAS if type_ == "schema" else True

    engine = create_engine(database_url)
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(
                conn,
                opts={"include_schemas": True, "include_name": include_name, "compare_type": True},
            )
            diff = compare_metadata(ctx, Base.metadata)
    finally:
        engine.dispose()
    assert diff == []


def test_openapi_schema_names_are_unique() -> None:
    """Two models with the same class name get module-qualified names in the OpenAPI
    document, which breaks the website's type aliases; keep response models uniquely named."""
    from reluai_api.main import create_app

    names = create_app().openapi()["components"]["schemas"]
    assert [n for n in names if "__" in n] == []
