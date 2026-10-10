"""Configuration for the AI CSV Analyst (env prefix ``RELUAI_CSV_``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CsvSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RELUAI_CSV_", env_file=".env", extra="ignore")

    # Bundled dataset, built at image build time from the verified canonical download.
    data_dir: Path = Path("/var/lib/reluai/data/csv")
    canonical_dir: Path = Path("/var/lib/reluai/data/canonical")

    # Visitor uploads live in the API container's tmpfs and are deleted after the TTL.
    upload_dir: Path = Path("/tmp/reluai-csv")  # noqa: S108 - private tmpfs inside the container
    upload_ttl_seconds: int = Field(default=3600, ge=60)
    upload_max_bytes: int = Field(default=2_000_000, ge=1024)
    upload_max_rows: int = Field(default=50_000, ge=1)
    upload_max_columns: int = Field(default=50, ge=1)
    max_stored_uploads: int = Field(default=50, ge=1)

    # Sandbox limits for every query.
    query_timeout_seconds: float = Field(default=5.0, gt=0)
    query_memory_limit: str = Field(default="256MB", pattern=r"^\d{1,5}(MB|GB)$")
    query_threads: int = Field(default=1, ge=1, le=4)

    visitor_asks_per_hour: int = Field(default=60, ge=1)
    visitor_uploads_per_hour: int = Field(default=10, ge=1)
    llm_max_retries: int = Field(default=2, ge=0, le=4)
    question_max_chars: int = Field(default=300, ge=20)

    @property
    def bundled_db(self) -> Path:
        return self.data_dir / "retail.duckdb"

    @property
    def bundled_profile(self) -> Path:
        return self.data_dir / "retail.profile.json"


@lru_cache(maxsize=1)
def get_csv_settings() -> CsvSettings:
    return CsvSettings()
