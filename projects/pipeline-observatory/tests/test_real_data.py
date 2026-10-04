"""Regression test on the real dataset (skipped unless it has been fetched).

December 2010 is the interesting month: the UCI workbook's two yearly sheets overlap on
1–9 December 2010, so those days arrive twice. The numbers below were measured on the
verified dataset and must not drift.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from reluai_core.db import Database
from reluai_core.errors import install_error_handlers
from reluai_datasets.materialize import canonical_paths, load_canonical
from reluai_datasets.online_retail import DATASET_ID
from reluai_pipeline.models import DqResult, PipelineRun
from reluai_pipeline.runner import create_run, execute_run
from reluai_pipeline.settings import PipelineSettings, get_pipeline_settings
from reluai_pipeline.sources import crm
from reluai_pipeline.sources.builder import build_sources

CANONICAL_DIR = Path(
    os.environ.get(
        "RELUAI_PIPELINE_CANONICAL_DIR", Path(__file__).resolve().parents[3] / "data/canonical"
    )
)
HAVE_DATA = canonical_paths(CANONICAL_DIR, DATASET_ID)[0].exists()

pytestmark = [
    pytest.mark.db,
    pytest.mark.slow,
    pytest.mark.skipif(not HAVE_DATA, reason="run `reluai-data fetch online-retail-ii` first"),
]


def test_december_2010_overlap_is_deduplicated(clean_db: Database, tmp_path: Path) -> None:
    df = load_canonical(CANONICAL_DIR, DATASET_ID)
    december = df[df["invoice_date"].dt.strftime("%Y-%m") == "2010-12"]
    build_sources(december, tmp_path, content_sha256="test")
    settings = PipelineSettings(
        sources_dir=tmp_path, crm_base_url="http://crm.test/internal/crm", crm_page_size=2000
    )
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(crm.router, prefix="/internal/crm")
    app.dependency_overrides[get_pipeline_settings] = lambda: settings

    run_id = create_run(clean_db, scenario="standard", trigger="cli")
    execute_run(
        clean_db,
        settings,
        run_id,
        client_factory=lambda: TestClient(app, base_url="http://crm.test"),
    )

    with clean_db.session() as s:
        run = s.get(PipelineRun, run_id)
        assert run is not None
        assert run.status == "succeeded", run.error_message
        assert run.rows_read == 65_004
        assert run.rows_deduplicated == 22_844
        assert run.rows_rejected == 447
        assert run.rows_inserted == run.rows_accepted == 65_004 - 447 - 22_844
        checks = {
            c.check_name: c.passed
            for c in s.scalars(select(DqResult).where(DqResult.run_id == run_id))
        }
    assert checks["duplicate_ratio"] is False  # flagged, published, explained
    assert checks["reject_ratio"] is True
    # Weighted pass rate with no previous drop loaded (so no drop_sequence check):
    # 17 of 19 weight points -> 89.5. In the full backfill it scores 90.0 (18/20).
    assert run.dq_score == 89.5
