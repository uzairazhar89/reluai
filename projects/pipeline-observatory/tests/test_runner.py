from __future__ import annotations

from collections.abc import Callable

import httpx
import pytest
from sqlalchemy import func, select, text

from reluai_core.db import Database
from reluai_pipeline import service
from reluai_pipeline.models import DqResult, PipelineRun, QuarantinedRow, RunLog, RunStep
from reluai_pipeline.runner import create_run, execute_run
from reluai_pipeline.settings import PipelineSettings

pytestmark = pytest.mark.db
Factory = Callable[[], httpx.Client]


def run(db: Database, settings: PipelineSettings, factory: Factory, scenario: str) -> PipelineRun:
    run_id = create_run(db, scenario=scenario, trigger="cli")
    execute_run(db, settings, run_id, client_factory=factory)
    with db.session() as s:
        row = s.get(PipelineRun, run_id)
        assert row is not None
        return row


def warehouse_lines(db: Database) -> int:
    with db.session() as s:
        return int(s.execute(text("SELECT count(*) FROM retail.invoice_line")).scalar_one())


def test_standard_run_publishes_and_records_everything(
    clean_db: Database, pipeline_settings: PipelineSettings, crm_client_factory: Factory
) -> None:
    r = run(clean_db, pipeline_settings, crm_client_factory, "standard")
    assert r.status == "succeeded", r.error_message
    assert r.drop_key == "2010-01"
    assert (r.rows_read, r.rows_rejected, r.rows_deduplicated, r.rows_inserted) == (12, 3, 1, 8)
    assert r.rows_unchanged == 0
    assert r.dq_score == 100.0
    assert r.environment and r.environment["cpu_count"]
    assert warehouse_lines(clean_db) == 8
    with clean_db.session() as s:
        steps = [
            x.name
            for x in s.scalars(
                select(RunStep).where(RunStep.run_id == r.id).order_by(RunStep.position)
            )
        ]
        assert steps == ["resolve", "extract", "validate", "transform", "quality_gate", "load"]
        assert (
            s.scalar(
                select(func.count())
                .select_from(QuarantinedRow)
                .where(QuarantinedRow.run_id == r.id)
            )
            == 4
        )
        assert (
            s.scalar(select(func.count()).select_from(DqResult).where(DqResult.run_id == r.id)) == 8
        )
        events = {x.event for x in s.scalars(select(RunLog).where(RunLog.run_id == r.id))}
        assert {"step.started", "drop.resolved", "run.published", "run.finished"} <= events
        kinds = dict(
            s.execute(text("SELECT kind, count(*) FROM retail.invoice GROUP BY kind")).all()
        )
        assert kinds == {"sale": 6, "cancellation": 1}


def test_runs_are_idempotent(
    clean_db: Database, pipeline_settings: PipelineSettings, crm_client_factory: Factory
) -> None:
    run(clean_db, pipeline_settings, crm_client_factory, "standard")
    replay = run(clean_db, pipeline_settings, crm_client_factory, "replay")
    assert replay.status == "succeeded"
    assert replay.drop_key == "2010-01"
    assert (replay.rows_inserted, replay.rows_unchanged) == (0, 8)
    assert warehouse_lines(clean_db) == 8


def test_next_drop_then_rotation(
    clean_db: Database, pipeline_settings: PipelineSettings, crm_client_factory: Factory
) -> None:
    first = run(clean_db, pipeline_settings, crm_client_factory, "standard")
    second = run(clean_db, pipeline_settings, crm_client_factory, "standard")
    third = run(clean_db, pipeline_settings, crm_client_factory, "standard")
    assert [first.drop_key, second.drop_key, third.drop_key] == ["2010-01", "2010-02", "2010-01"]
    assert third.note and "re-processing" in third.note
    assert third.rows_inserted == 0


def test_flaky_source_recovers_with_retries(
    clean_db: Database, pipeline_settings: PipelineSettings, crm_client_factory: Factory
) -> None:
    r = run(clean_db, pipeline_settings, crm_client_factory, "crm_flaky")
    assert r.status == "succeeded"
    assert r.source_retries >= 2  # two failures per page


def test_outage_fails_before_writing(
    clean_db: Database, pipeline_settings: PipelineSettings, crm_client_factory: Factory
) -> None:
    r = run(clean_db, pipeline_settings, crm_client_factory, "crm_outage")
    assert (r.status, r.failure_step) == ("failed", "extract")
    assert r.source_retries == pipeline_settings.crm_max_attempts - 1
    assert "CRM unavailable" in (r.error_message or "")
    assert warehouse_lines(clean_db) == 0


def test_corrupt_drop_fails_quality_gate_and_publishes_nothing(
    clean_db: Database, pipeline_settings: PipelineSettings, crm_client_factory: Factory
) -> None:
    strict = pipeline_settings.model_copy(update={"reject_ratio_gate": 0.01})
    r = run(clean_db, strict, crm_client_factory, "corrupt_drop")
    assert (r.status, r.failure_step) == ("failed", "quality_gate")
    assert warehouse_lines(clean_db) == 0
    with clean_db.session() as s:
        gate = s.scalars(
            select(DqResult).where(DqResult.run_id == r.id, DqResult.check_name == "reject_ratio")
        ).one()
        assert gate.passed is False
        statuses = {
            x.name: x.status for x in s.scalars(select(RunStep).where(RunStep.run_id == r.id))
        }
        assert statuses["quality_gate"] == "failed"
        assert statuses["load"] == "skipped"


def test_summary_and_detail_read_models(
    clean_db: Database, pipeline_settings: PipelineSettings, crm_client_factory: Factory
) -> None:
    ok = run(clean_db, pipeline_settings, crm_client_factory, "standard")
    run(clean_db, pipeline_settings, crm_client_factory, "crm_outage")
    summary = service.summary(clean_db, pipeline_settings)
    assert summary.runs_total == 2
    assert summary.failures_recent == 1
    assert summary.last_success and summary.last_success.id == ok.id
    assert summary.drops_loaded == 1 and summary.drops_total == 2
    assert summary.warehouse.invoice_lines == 8
    assert len(summary.trend) == 2
    detail = service.run_detail(clean_db, ok.id)
    assert detail is not None
    assert {r.code for r in detail.reasons} >= {"stock_adjustment", "duplicate_line"}
    assert {w.code for w in detail.warnings} >= {"missing_customer_id"}
    page = service.quarantine_page(clean_db, ok.id, reason="duplicate_line", limit=10, offset=0)
    assert page.total == 1
    assert page.items[0].raw["StockCode"] == "71053"


def test_results_aggregate_latest_successful_run_per_drop(
    clean_db: Database, pipeline_settings: PipelineSettings, crm_client_factory: Factory
) -> None:
    run(clean_db, pipeline_settings, crm_client_factory, "standard")  # 2010-01
    run(clean_db, pipeline_settings, crm_client_factory, "standard")  # 2010-02
    run(clean_db, pipeline_settings, crm_client_factory, "crm_outage")
    replay = run(clean_db, pipeline_settings, crm_client_factory, "replay")  # 2010-02 again
    res = service.results(clean_db)
    assert [d.drop_key for d in res.drops] == ["2010-01", "2010-02"]
    assert res.drops[1].run_id == replay.id
    assert res.totals.rows_read == 12 + 3
    assert res.totals.rows_published == 8 + 3
    assert (res.runs_succeeded, res.runs_failed) == (3, 1)
    assert res.duration.median_ms is not None
    assert res.environment is not None
