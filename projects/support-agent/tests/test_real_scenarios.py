"""The full scenario suite on the real order data (needs the verified dataset and PostgreSQL).

CI's datasets job fetches Online Retail II and runs the ``slow`` tests with a database.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from reluai_core.db import Database
from reluai_support import service
from reluai_support.agent import scripted_chain
from reluai_support.evaluation import run_evaluation
from reluai_support.orders import build_orders
from reluai_support.scenarios import SCENARIOS
from reluai_support.settings import SupportSettings

CANONICAL_DIR = Path(
    os.environ.get(
        "RELUAI_PIPELINE_CANONICAL_DIR", Path(__file__).resolve().parents[3] / "data/canonical"
    )
)
pytestmark = [
    pytest.mark.slow,
    pytest.mark.db,
    pytest.mark.skipif(
        not (CANONICAL_DIR / "online-retail-ii.parquet").is_file(),
        reason="canonical dataset not fetched",
    ),
]


def test_every_scenario_passes_with_the_scripted_agent(tmp_path: Path, clean_db: Database) -> None:
    build_orders(CANONICAL_DIR, tmp_path)
    settings = SupportSettings(data_dir=tmp_path)
    service._indexed.clear()
    summary = run_evaluation(
        lambda cf: service.runtime(clean_db, settings, cf, None), scripted_chain, label="scripted"
    )
    failed = {r.id: r.failures for r in summary.results if not r.passed}
    assert failed == {}
    assert summary.scenarios == len(SCENARIOS)
    assert summary.providers == ["scripted"]
