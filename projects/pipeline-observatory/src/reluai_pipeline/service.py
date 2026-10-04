"""Read models and visitor-run admission for the API."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import case, func, select, text
from sqlalchemy.dialects.postgresql import distinct_on

from reluai_core.cpu_lease import lease_status
from reluai_core.db import Database
from reluai_core.ratelimit import consume_quota
from reluai_pipeline.models import (
    DqResult,
    PipelineRun,
    QuarantinedRow,
    RunLog,
    RunStep,
    SourceDrop,
)
from reluai_pipeline.rules import REASONS
from reluai_pipeline.runner import create_run
from reluai_pipeline.scenarios import SCENARIOS
from reluai_pipeline.schemas import (
    DqOut,
    DropOut,
    DropResult,
    DurationStats,
    LogOut,
    QuarantinePage,
    QuarantineRowOut,
    ReasonCount,
    ResultsOut,
    ResultsTotals,
    RunDetailOut,
    RunOut,
    StepOut,
    SummaryOut,
    TrendPoint,
    WarehouseStats,
)
from reluai_pipeline.settings import PipelineSettings
from reluai_pipeline.sources.builder import load_index

RECENT_WINDOW = 30
PENDING = ("queued", "running")


class UnknownScenarioError(ValueError):
    pass


class RunQuotaExceededError(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__("visitor run quota exceeded")
        self.retry_after = retry_after


class RunQueueFullError(Exception):
    pass


def pending_runs(db: Database) -> int:
    with db.session() as s:
        return int(
            s.scalar(
                select(func.count()).select_from(PipelineRun).where(PipelineRun.status.in_(PENDING))
            )
            or 0
        )


def admit_visitor_run(
    db: Database,
    settings: PipelineSettings,
    *,
    scenario: str,
    visitor: str,
    defer: Callable[[uuid.UUID], None],
) -> tuple[uuid.UUID, int]:
    """Check quota and queue capacity, create the run and hand it to the job queue."""
    if scenario not in SCENARIOS:
        raise UnknownScenarioError(scenario)
    with db.session() as s:
        quota = consume_quota(
            s,
            key=f"pipeline-run:{visitor}",
            limit=settings.visitor_runs_per_hour,
            window=timedelta(hours=1),
        )
    if not quota.allowed:
        raise RunQuotaExceededError(quota.retry_after_seconds)
    pending = pending_runs(db)
    if pending >= settings.max_pending_runs:
        raise RunQueueFullError
    run_id = create_run(db, scenario=scenario, trigger="visitor", visitor_key=visitor)
    defer(run_id)
    return run_id, pending + 1


def summary(db: Database, settings: PipelineSettings) -> SummaryOut:
    try:
        drops_total = len(load_index(settings.sources_dir).drops)
    except FileNotFoundError:
        drops_total = 0
    with db.session() as s:
        last = s.scalars(
            select(PipelineRun)
            .where(PipelineRun.status.notin_(PENDING))
            .order_by(PipelineRun.finished_at.desc())
            .limit(1)
        ).first()
        last_ok = s.scalars(
            select(PipelineRun)
            .where(PipelineRun.status == "succeeded")
            .order_by(PipelineRun.finished_at.desc())
            .limit(1)
        ).first()
        recent = list(
            s.scalars(
                select(PipelineRun)
                .where(PipelineRun.status.notin_(PENDING))
                .order_by(PipelineRun.finished_at.desc())
                .limit(RECENT_WINDOW)
            )
        )
        runs_total = int(s.scalar(select(func.count()).select_from(PipelineRun)) or 0)
        pending = int(
            s.scalar(
                select(func.count()).select_from(PipelineRun).where(PipelineRun.status.in_(PENDING))
            )
            or 0
        )
        drops_loaded = int(s.scalar(select(func.count()).select_from(SourceDrop)) or 0)
        wh = s.execute(
            text("""
            SELECT (SELECT count(*) FROM retail.invoice_line),
                   (SELECT count(*) FROM retail.invoice),
                   (SELECT count(*) FROM retail.customer),
                   (SELECT count(*) FROM retail.product),
                   (SELECT coalesce(sum(line_total), 0) FROM retail.invoice_line)
        """)
        ).one()
    lease = lease_status(db.engine)
    return SummaryOut(
        last_run=RunOut.model_validate(last) if last else None,
        last_success=RunOut.model_validate(last_ok) if last_ok else None,
        runs_total=runs_total,
        failures_recent=sum(1 for r in recent if r.status == "failed"),
        recent_window=len(recent),
        drops_loaded=drops_loaded,
        drops_total=drops_total,
        warehouse=WarehouseStats(
            invoice_lines=wh[0],
            invoices=wh[1],
            customers=wh[2],
            products=wh[3],
            net_revenue_gbp=float(wh[4]),
        ),
        pending_runs=pending,
        lease_holder=lease.holder,
        trend=[
            TrendPoint(
                id=r.id,
                started_at=r.started_at,
                status=r.status,
                scenario=r.scenario,
                drop_key=r.drop_key,
                dq_score=r.dq_score,
                duration_ms=r.duration_ms,
                rows_read=r.rows_read,
                rows_rejected=r.rows_rejected,
            )
            for r in reversed(recent)
        ],
    )


def list_runs(db: Database, limit: int) -> list[RunOut]:
    with db.session() as s:
        rows = s.scalars(select(PipelineRun).order_by(PipelineRun.queued_at.desc()).limit(limit))
        return [RunOut.model_validate(r) for r in rows]


def run_detail(db: Database, run_id: uuid.UUID) -> RunDetailOut | None:
    with db.session() as s:
        run = s.get(PipelineRun, run_id)
        if run is None:
            return None
        steps = s.scalars(
            select(RunStep).where(RunStep.run_id == run_id).order_by(RunStep.position)
        )
        checks = s.scalars(select(DqResult).where(DqResult.run_id == run_id).order_by(DqResult.id))
        logs = s.scalars(
            select(RunLog).where(RunLog.run_id == run_id).order_by(RunLog.id).limit(500)
        )
        counts = s.execute(
            select(QuarantinedRow.reason_code, func.count())
            .where(QuarantinedRow.run_id == run_id)
            .group_by(QuarantinedRow.reason_code)
            .order_by(func.count().desc())
        ).all()
        step_list = [StepOut.model_validate(x) for x in steps]
        detail = RunDetailOut(
            run=RunOut.model_validate(run),
            steps=step_list,
            checks=[DqOut.model_validate(x) for x in checks],
            reasons=[_reason(code, int(n)) for code, n in counts],
            warnings=[],
            logs=[LogOut.model_validate(x) for x in logs],
            environment=run.environment,
        )
    validate_step = next((x for x in step_list if x.name == "validate"), None)
    if validate_step and validate_step.detail:
        warn = validate_step.detail.get("warnings", {})
        detail.warnings = [
            _reason(code, int(n)) for code, n in sorted(warn.items(), key=lambda kv: -int(kv[1]))
        ]
    return detail


def _reason(code: str, count: int) -> ReasonCount:
    r = REASONS.get(code)
    return ReasonCount(
        code=code,
        label=r.label if r else code,
        severity=r.severity.value if r else "reject",
        explanation=r.explanation if r else "",
        count=count,
    )


def quarantine_page(
    db: Database, run_id: uuid.UUID, *, reason: str | None, limit: int, offset: int
) -> QuarantinePage:
    with db.session() as s:
        q = select(QuarantinedRow).where(QuarantinedRow.run_id == run_id)
        c = select(func.count()).select_from(QuarantinedRow).where(QuarantinedRow.run_id == run_id)
        if reason:
            q = q.where(QuarantinedRow.reason_code == reason)
            c = c.where(QuarantinedRow.reason_code == reason)
        total = int(s.scalar(c) or 0)
        rows = s.scalars(q.order_by(QuarantinedRow.line_number).limit(limit).offset(offset))
        return QuarantinePage(total=total, items=[QuarantineRowOut.model_validate(r) for r in rows])


def drops(db: Database, settings: PipelineSettings) -> list[DropOut]:
    try:
        index = load_index(settings.sources_dir)
    except FileNotFoundError:
        return []
    with db.session() as s:
        loaded = {d.drop_key: d for d in s.scalars(select(SourceDrop))}
    return [
        DropOut(
            key=d.key,
            rows=d.rows,
            loaded=d.key in loaded,
            first_loaded_at=loaded[d.key].first_loaded_at if d.key in loaded else None,
            times_processed=loaded[d.key].times_processed if d.key in loaded else 0,
        )
        for d in index.drops
    ]


def status_counts(db: Database) -> dict[str, int]:
    with db.session() as s:
        row = s.execute(
            select(
                func.count(),
                func.sum(case((PipelineRun.status == "failed", 1), else_=0)),
            ).select_from(PipelineRun)
        ).one()
    return {"runs": int(row[0] or 0), "failed": int(row[1] or 0)}


def results(db: Database) -> ResultsOut:
    """Latest successful run per drop, with duration percentiles across those runs."""
    with db.session() as s:
        latest = list(
            s.scalars(
                select(PipelineRun)
                .where(PipelineRun.status == "succeeded", PipelineRun.drop_key.is_not(None))
                .order_by(PipelineRun.drop_key, PipelineRun.finished_at.desc())
                .ext(distinct_on(PipelineRun.drop_key))
            )
        )
        counts = dict(
            s.execute(
                select(PipelineRun.status, func.count())
                .where(PipelineRun.status.in_(("succeeded", "failed")))
                .group_by(PipelineRun.status)
            ).all()
        )
    drops = [
        DropResult(
            drop_key=r.drop_key or "",
            run_id=r.id,
            finished_at=r.finished_at,
            rows_read=r.rows_read,
            rows_rejected=r.rows_rejected,
            rows_deduplicated=r.rows_deduplicated,
            rows_published=r.rows_accepted,
            dq_score=r.dq_score,
            duration_ms=r.duration_ms,
        )
        for r in latest
    ]
    durations = sorted(r.duration_ms for r in latest if r.duration_ms is not None)

    def pct(q: float) -> int | None:
        if not durations:
            return None
        return durations[min(len(durations) - 1, round(q * (len(durations) - 1)))]

    newest = max(latest, key=lambda r: r.finished_at or r.queued_at, default=None)
    return ResultsOut(
        drops=drops,
        totals=ResultsTotals(
            drops=len(drops),
            rows_read=sum(d.rows_read for d in drops),
            rows_rejected=sum(d.rows_rejected for d in drops),
            rows_deduplicated=sum(d.rows_deduplicated for d in drops),
            rows_published=sum(d.rows_published for d in drops),
        ),
        duration=DurationStats(
            median_ms=pct(0.5), p95_ms=pct(0.95), max_ms=durations[-1] if durations else None
        ),
        environment=newest.environment if newest else None,
        runs_succeeded=int(counts.get("succeeded", 0)),
        runs_failed=int(counts.get("failed", 0)),
    )
