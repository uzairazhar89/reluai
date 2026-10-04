from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from reluai_core.settings import CoreSettings, Environment


def test_plain_postgres_url_gets_driver_tag() -> None:
    s = CoreSettings(database_url="postgresql://u:p@h:5432/d")
    assert s.database_url == "postgresql+psycopg://u:p@h:5432/d"
    assert s.libpq_dsn == "postgresql://u:p@h:5432/d"


def test_non_postgres_url_rejected() -> None:
    with pytest.raises(ValidationError):
        CoreSettings(database_url="sqlite:///x.db")


def test_migration_url_defaults_to_runtime_url() -> None:
    s = CoreSettings(database_url="postgresql://app@h/d")
    assert s.migration_url == s.database_url
    s2 = CoreSettings(
        database_url="postgresql://app@h/d", migration_database_url="postgresql://owner@h/d"
    )
    assert s2.migration_url == "postgresql+psycopg://owner@h/d"


def test_production_requires_real_visitor_secret() -> None:
    with pytest.raises(ValidationError, match="VISITOR_HASH_SECRET"):
        CoreSettings(environment=Environment.PROD)
    ok = CoreSettings(environment=Environment.PROD, visitor_hash_secret=SecretStr("x" * 32))
    assert ok.json_logs is True
    assert ok.docs_enabled is False


def test_dev_defaults_are_developer_friendly() -> None:
    s = CoreSettings(environment=Environment.DEV)
    assert s.json_logs is False
    assert s.docs_enabled is True
