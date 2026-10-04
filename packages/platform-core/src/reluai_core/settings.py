"""Typed runtime configuration shared by every service (API, worker, CLI).

All values come from environment variables prefixed ``RELUAI_`` (or a ``.env`` file in
development). Project modules define their own settings classes with their own prefixes.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_DEV_SECRET = "dev-only-not-secret"  # noqa: S105 - placeholder; rejected outside dev/test


class Environment(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PROD = "prod"


class CoreSettings(BaseSettings):
    """Platform-wide settings."""

    model_config = SettingsConfigDict(env_prefix="RELUAI_", env_file=".env", extra="ignore")

    environment: Environment = Environment.DEV
    service_name: str = "reluai"
    version: str = Field(default="0.0.0-dev", description="Build version (git SHA in images)")

    database_url: str = "postgresql+psycopg://reluai:reluai@localhost:5432/reluai"
    migration_database_url: str | None = Field(
        default=None,
        description="Schema-owner connection used only by migrations (defaults to database_url)",
    )
    db_pool_size: int = Field(default=5, ge=1, le=50)
    db_max_overflow: int = Field(default=5, ge=0, le=50)
    db_statement_timeout_ms: int = Field(default=15_000, ge=100)

    log_level: str = "INFO"
    log_json: bool | None = Field(default=None, description="Default: JSON everywhere except dev")

    site_url: str = "https://reluai.cloud"
    data_dir: Path = Path("/var/lib/reluai/data")

    max_request_body_bytes: int = Field(default=1_048_576, ge=1024)
    cpu_lease_wait_seconds: float = Field(default=600.0, ge=0)
    queue_depth_limit: int = Field(default=5, ge=1)
    min_free_disk_bytes: int = Field(default=500 * 1024 * 1024, ge=0)
    expose_api_docs: bool | None = Field(default=None, description="Default: off in prod")
    visitor_hash_secret: SecretStr = Field(
        default=SecretStr(_DEV_SECRET),
        description="Keyed hash for anonymous per-visitor limits (IP addresses are never stored)",
    )

    @model_validator(mode="after")
    def _require_real_secret_outside_dev(self) -> CoreSettings:
        if (
            self.environment in {Environment.STAGING, Environment.PROD}
            and self.visitor_hash_secret.get_secret_value() == _DEV_SECRET
        ):
            raise ValueError("RELUAI_VISITOR_HASH_SECRET must be set in staging and production")
        return self

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def _require_postgres(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if not v.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ValueError("database_url must be a PostgreSQL URL (postgresql+psycopg://...)")
        if v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v.removeprefix("postgresql://")
        return v

    @property
    def migration_url(self) -> str:
        return self.migration_database_url or self.database_url

    @property
    def libpq_dsn(self) -> str:
        """Plain libpq connection string for psycopg/procrastinate (no SQLAlchemy driver tag)."""
        return "postgresql://" + self.database_url.removeprefix("postgresql+psycopg://")

    @property
    def json_logs(self) -> bool:
        return self.log_json if self.log_json is not None else self.environment != Environment.DEV

    @property
    def docs_enabled(self) -> bool:
        if self.expose_api_docs is not None:
            return self.expose_api_docs
        return self.environment != Environment.PROD


@lru_cache(maxsize=1)
def get_core_settings() -> CoreSettings:
    return CoreSettings()
