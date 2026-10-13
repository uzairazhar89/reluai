"""Configuration for Document Intelligence (env prefix ``RELUAI_DOCS_``)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class DocsSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RELUAI_DOCS_", env_file=".env", extra="ignore")

    # Built at image build time: the bundled sample PDF (pre-extracted) and the embedding model.
    data_dir: Path = Path("/var/lib/reluai/data/docs")
    # Uploaded PDFs wait here, in memory only, until the worker reads them (a tmpfs volume
    # shared by the api and worker containers). Each file is deleted as soon as it is read.
    spool_dir: Path = Path("/run/reluai/doc-spool")

    # Upload limits.
    upload_max_bytes: int = Field(default=10 * 1024 * 1024, ge=1024)
    max_pages: int = Field(default=60, ge=1, le=500)
    max_chars: int = Field(default=300_000, ge=1000)
    max_ocr_pages: int = Field(default=5, ge=0, le=60)
    ocr_dpi: int = Field(default=150, ge=72, le=300)
    ocr_max_pixels: int = Field(default=6_000_000, ge=500_000)

    # The isolated reader process: wall-clock and CPU time, and memory (address space).
    read_timeout_seconds: float = Field(default=60.0, gt=0)
    read_cpu_seconds: int = Field(default=90, ge=5)
    read_memory_mb: int = Field(default=1536, ge=256)
    lease_wait_seconds: float = Field(default=90.0, ge=0)
    max_pending: int = Field(default=6, ge=1, description="Uploads waiting or in progress")

    # Chunking and retrieval.
    chunk_words: int = Field(default=150, ge=40, le=400)
    chunk_overlap: int = Field(default=1, ge=0, le=3)
    candidates: int = Field(default=20, ge=5, le=50)
    passages: int = Field(default=6, ge=1, le=12)
    embed_threads: int = Field(default=2, ge=1, le=8)

    # Visitor quotas and retention.
    visitor_uploads_per_hour: int = Field(default=5, ge=1)
    visitor_questions_per_hour: int = Field(default=30, ge=1)
    upload_ttl_minutes: int = Field(default=60, ge=5)
    question_max_chars: int = Field(default=300, ge=20)

    @property
    def model_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def sample_path(self) -> Path:
        return self.data_dir / "sample.json"


@lru_cache(maxsize=1)
def get_docs_settings() -> DocsSettings:
    return DocsSettings()
