"""Shared pytest fixtures.

Database tests need ``TEST_DATABASE_URL`` pointing at a PostgreSQL 16 server where the user
may create databases (CI uses a pgvector service container). Each test session creates a
fresh database, applies the real migrations and drops it afterwards.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from reluai_core.db import Database
from reluai_core.settings import CoreSettings, Environment

ADMIN_URL = os.environ.get("TEST_DATABASE_URL")
pytest_plugins = ["reluai_pipeline.testing"]


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if ADMIN_URL:
        return
    skip = pytest.mark.skip(reason="TEST_DATABASE_URL not set")
    for item in items:
        if "db" in item.keywords:
            item.add_marker(skip)


def _swap_db(url: str, name: str) -> str:
    base, _, _ = url.rpartition("/")
    return f"{base}/{name}"


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    assert ADMIN_URL, "database fixtures require TEST_DATABASE_URL"
    admin_url = ADMIN_URL.replace("postgresql://", "postgresql+psycopg://", 1)
    name = f"reluai_test_{uuid.uuid4().hex[:8]}"
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = _swap_db(admin_url, name)
    try:
        from alembic import command
        from alembic.config import Config

        cfg = Config()
        cfg.set_main_option(
            "script_location", str(Path(__file__).parent / "apps/api/src/reluai_api/migrations")
        )
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(
                text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :n"),
                {"n": name},
            )
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
        admin.dispose()


@pytest.fixture(scope="session")
def core_settings(database_url: str, tmp_path_factory: pytest.TempPathFactory) -> CoreSettings:
    return CoreSettings(
        environment=Environment.TEST,
        database_url=database_url,
        data_dir=tmp_path_factory.mktemp("data"),
        log_json=False,
        cpu_lease_wait_seconds=2,
    )


@pytest.fixture(scope="session")
def db(core_settings: CoreSettings) -> Iterator[Database]:
    database = Database(core_settings, application_name="pytest")
    yield database
    database.dispose()


@pytest.fixture
def clean_db(db: Database) -> Database:
    """Empty every application table before the test."""
    with db.session() as s:
        s.execute(
            text(
                "TRUNCATE pipeline.run, pipeline.source_drop, retail.invoice_line, retail.invoice, "
                "retail.customer, retail.product, platform.rate_counter, platform.llm_usage "
                "RESTART IDENTITY CASCADE"
            )
        )
    return db
