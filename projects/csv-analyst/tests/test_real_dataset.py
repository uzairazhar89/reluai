"""The evaluation on the real bundled table (skipped unless the canonical data is present).

CI's datasets job fetches and verifies Online Retail II, then runs the ``slow`` tests.
Locally: ``reluai-data fetch online-retail-ii --out data/canonical``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from reluai_csv.datasets import build_bundled
from reluai_csv.evaluation import run_evaluation
from reluai_csv.settings import CsvSettings

CANONICAL_DIR = Path(
    os.environ.get(
        "RELUAI_PIPELINE_CANONICAL_DIR", Path(__file__).resolve().parents[3] / "data/canonical"
    )
)
pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(
        not (CANONICAL_DIR / "online-retail-ii.parquet").is_file(),
        reason="canonical dataset not fetched",
    ),
]


def test_development_set_on_the_real_table(tmp_path: Path) -> None:
    build_bundled(CANONICAL_DIR, tmp_path)
    summary = run_evaluation(CsvSettings(data_dir=tmp_path), record=False)
    assert summary["environment"]["rows"] == 1_067_371
    assert summary["wrong"] == 0
    assert summary["declined_unexpected"] == 0
    # The held-out set is measured and published, not asserted: see test_parser.py.
    assert summary["held_out"]["questions"] > 0
