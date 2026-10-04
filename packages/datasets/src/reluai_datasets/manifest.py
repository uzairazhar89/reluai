"""The artifact manifest: every third-party dataset, its licence and how to verify it.

``artifacts/manifest.yaml`` is the single source of truth used by the fetch CLI, CI checks
and the website's /data page.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Licence(_Strict):
    name: str
    url: HttpUrl
    attribution: str = Field(description="Exact credit line shown wherever the data is used")
    notes: str | None = None


class Source(_Strict):
    kind: Literal["uci_zip_xlsx", "rda"]
    url: HttpUrl
    role: Literal["canonical", "mirror"]
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    max_bytes: int = Field(default=200 * 1024 * 1024, gt=0)
    notes: str | None = None


class ContentChecks(_Strict):
    rows: int
    columns: list[str]
    min_timestamp: datetime
    max_timestamp: datetime
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fingerprint_version: int = 1


class Dataset(_Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    title: str
    publisher: str
    homepage: HttpUrl
    doi: str | None = None
    description: str
    real_data: bool
    modifications: list[str] = Field(default_factory=list)
    licence: Licence
    sources: list[Source]
    checks: ContentChecks
    used_by: list[str] = Field(default_factory=list)


class Manifest(_Strict):
    version: int
    datasets: list[Dataset]

    def get(self, dataset_id: str) -> Dataset:
        for ds in self.datasets:
            if ds.id == dataset_id:
                return ds
        raise KeyError(f"Unknown dataset {dataset_id!r}")


def default_manifest_path() -> Path:
    """``artifacts/manifest.yaml`` at the repository root (or ``RELUAI_MANIFEST`` in images)."""
    import os

    env = os.environ.get("RELUAI_MANIFEST")
    if env:
        return Path(env)
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "artifacts" / "manifest.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("artifacts/manifest.yaml not found; set RELUAI_MANIFEST")


def load_manifest(path: Path | None = None) -> Manifest:
    raw = yaml.safe_load((path or default_manifest_path()).read_text(encoding="utf-8"))
    return Manifest.model_validate(raw)
