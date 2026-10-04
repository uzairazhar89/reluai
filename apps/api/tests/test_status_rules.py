from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from reluai_api.status import _pipeline_component
from reluai_pipeline.models import PipelineRun


def _run(status: str, *, simulated: bool, hours_ago: float) -> PipelineRun:
    return PipelineRun(
        status=status,
        simulated=simulated,
        finished_at=datetime.now(UTC) - timedelta(hours=hours_ago),
    )


@pytest.mark.parametrize(
    ("status", "simulated", "hours_ago", "expected"),
    [
        ("succeeded", False, 1, "operational"),
        ("failed", True, 0.1, "operational"),  # fault scenarios are meant to fail
        ("failed", False, 0.1, "degraded"),  # a real run failed
        ("succeeded", False, 14, "degraded"),  # the schedule has stopped
    ],
)
def test_pipeline_component(status: str, simulated: bool, hours_ago: float, expected: str) -> None:
    component = _pipeline_component(_run(status, simulated=simulated, hours_ago=hours_ago))
    assert component.status == expected


def test_detail_is_readable() -> None:
    detail = _pipeline_component(_run("failed", simulated=True, hours_ago=0.05)).detail
    assert detail == "Last run finished 3 min ago: failed as designed (simulated fault)"
