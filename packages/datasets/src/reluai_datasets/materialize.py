"""Fetch a dataset from its listed sources, verify it and store a canonical Parquet copy.

Sources are tried in manifest order (canonical first). A source is accepted only when its
content passes the manifest checks; the provenance record says which one was used.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from reluai_core.logging import get_logger
from reluai_datasets import online_retail
from reluai_datasets.fetch import DownloadError, download, sha256_file
from reluai_datasets.manifest import Dataset, Source

log = get_logger(__name__)

Reader = Callable[[Path], pd.DataFrame]
READERS: dict[str, Reader] = {
    "uci_zip_xlsx": online_retail.read_uci_zip,
    "rda": online_retail.read_rda,
}


class Provenance(BaseModel):
    dataset_id: str
    source_url: str
    source_role: str
    source_sha256: str
    content_sha256: str
    rows: int
    retrieved_at: datetime
    licence: str
    attribution: str


class MaterializeError(RuntimeError):
    pass


def canonical_paths(out_dir: Path, dataset_id: str) -> tuple[Path, Path]:
    return out_dir / f"{dataset_id}.parquet", out_dir / f"{dataset_id}.provenance.json"


def _try_source(ds: Dataset, src: Source, work_dir: Path) -> tuple[pd.DataFrame, Provenance]:
    suffix = ".zip" if src.kind == "uci_zip_xlsx" else ".rda"
    raw_path = work_dir / f"{ds.id}-{src.role}{suffix}"
    if raw_path.exists() and (src.sha256 is None or sha256_file(raw_path) == src.sha256):
        file_sha = sha256_file(raw_path)
    else:
        file_sha = download(
            str(src.url), raw_path, max_bytes=src.max_bytes, expected_sha256=src.sha256
        )
    df = READERS[src.kind](raw_path)
    content_sha = online_retail.verify(df, ds.checks)
    prov = Provenance(
        dataset_id=ds.id,
        source_url=str(src.url),
        source_role=src.role,
        source_sha256=file_sha,
        content_sha256=content_sha,
        rows=len(df),
        retrieved_at=datetime.now(UTC),
        licence=ds.licence.name,
        attribution=ds.licence.attribution.strip(),
    )
    return df, prov


def materialize(
    ds: Dataset, out_dir: Path, *, prefer: str | None = None, force: bool = False
) -> Provenance:
    """Ensure ``out_dir/<id>.parquet`` exists and is verified; return its provenance."""
    parquet_path, prov_path = canonical_paths(out_dir, ds.id)
    if parquet_path.exists() and prov_path.exists() and not force:
        prov = Provenance.model_validate_json(prov_path.read_text(encoding="utf-8"))
        if prov.content_sha256 == ds.checks.content_sha256:
            return prov

    out_dir.mkdir(parents=True, exist_ok=True)
    sources = sorted(ds.sources, key=lambda s: (s.role != prefer) if prefer else 0)
    errors: list[str] = []
    for src in sources:
        try:
            df, prov = _try_source(ds, src, out_dir)
        except (DownloadError, online_retail.ContentMismatchError, OSError, ValueError) as exc:
            log.warning("dataset.source_rejected", dataset=ds.id, source=src.role, error=str(exc))
            errors.append(f"{src.role}: {exc}")
            continue
        df.to_parquet(parquet_path, index=False, compression="zstd")
        prov_path.write_text(
            json.dumps(prov.model_dump(mode="json"), indent=2) + "\n", encoding="utf-8"
        )
        log.info("dataset.materialized", dataset=ds.id, source=src.role, rows=prov.rows)
        return prov
    raise MaterializeError(f"No source for {ds.id} passed verification: " + " | ".join(errors))


def load_canonical(out_dir: Path, dataset_id: str) -> pd.DataFrame:
    parquet_path, _ = canonical_paths(out_dir, dataset_id)
    if not parquet_path.exists():
        raise FileNotFoundError(f"{parquet_path} missing; run `reluai-data fetch {dataset_id}`")
    return pd.read_parquet(parquet_path)
