"""Configuration for the Data Pipeline Observatory (env prefix ``RELUAI_PIPELINE_``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class PipelineSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RELUAI_PIPELINE_", env_file=".env", extra="ignore"
    )

    canonical_dir: Path = Path("/var/lib/reluai/data/canonical")
    sources_dir: Path = Path("/var/lib/reluai/data/pipeline/sources")

    crm_base_url: str = "http://api:8000/internal/crm"
    crm_page_size: int = Field(default=500, ge=1, le=2000)
    crm_max_attempts: int = Field(default=4, ge=1, le=10)
    crm_timeout_seconds: float = Field(default=5.0, gt=0)
    crm_backoff_initial_seconds: float = Field(default=0.5, ge=0)
    crm_backoff_max_seconds: float = Field(default=4.0, ge=0)

    reject_ratio_gate: float = Field(default=0.05, gt=0, lt=1)
    duplicate_ratio_warn: float = Field(default=0.05, gt=0, lt=1)
    customer_completeness_min: float = Field(default=0.60, ge=0, le=1)

    visitor_runs_per_hour: int = Field(default=3, ge=1)
    max_pending_runs: int = Field(default=4, ge=1)
    schedule_cron: str = "17 */6 * * *"
    quarantine_store_limit: int = Field(default=20_000, ge=100)


@lru_cache(maxsize=1)
def get_pipeline_settings() -> PipelineSettings:
    return PipelineSettings()
