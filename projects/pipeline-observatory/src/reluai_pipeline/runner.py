"""Pipeline orchestration.

One run = resolve → extract → validate → transform → quality gate → load (+ warehouse
checks). Every step is timed, logged and persisted by :class:`RunRecorder`; any failure is
classified, recorded on the run and leaves the warehouse untouched.
"""

from __future__ import annotations

import calendar
import os
import platform
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from importlib import metadata
from typing import Any

import httpx
import pandas as pd
from sqlalchemy import func, insert, select, update

from reluai_core.db import Database
from reluai_core.logging import get_logger
from reluai_pipeline.contract import ParsedDrop, SchemaMismatchError, parse_drop
from reluai_pipeline.extract import (
    CrmResult,
    CrmUnavailableError,
    corrupt_drop,
    fetch_customers,
    read_catalogue,
    read_drop_file,
)
from reluai_pipeline.load import ReconciliationError, load_batch
from reluai_pipeline.models import DqResult, PipelineRun, QuarantinedRow, SourceDrop
from reluai_pipeline.quality import (
    CheckResult,
    batch_checks,
    dq_score,
    schema_check,
    warehouse_checks,
)
from reluai_pipeline.recorder import RunRecorder
from reluai_pipeline.scenarios import SCENARIOS
from reluai_pipeline.settings import PipelineSettings
from reluai_pipeline.sources.builder import DropInfo, load_index
from reluai_pipeline.transform import Transformed, transform
from reluai_pipeline.validate import ReferenceData, ValidationResult, validate

log = get_logger(__name__)
ClientFactory = Callable[[], httpx.Client]
SIMULATED_CRM_FAULTS = {"crm_flaky": "flaky", "crm_outage": "outage"}


class QualityGateError(RuntimeError):
    """A gate-severity check failed; nothing is published."""


@dataclass(frozen=True, slots=True)
class RunOutcome:
    run_id: uuid.UUID
    status: str
    drop_key: str | None
    rows_read: int
    rows_inserted: int
    rows_rejected: int
    dq_score: float | None
    failure_step: str | None
    duration_ms: int


@dataclass(slots=True)
class RunState:
    """Everything a run accumulates; written to ``pipeline.run`` when it finishes."""

    rows_read: int = 0
    rows_accepted: int = 0
    rows_rejected: int = 0
    rows_deduplicated: int = 0
    rows_warned: int = 0
    rows_inserted: int = 0
    rows_unchanged: int = 0
    source_retries: int = 0
    note: str | None = None
    drop_key: str | None = None
    status: str = "succeeded"
    failure_step: str | None = None
    error: str | None = None
    checks: list[CheckResult] = field(default_factory=list)
    quarantine: pd.DataFrame = field(default_factory=pd.DataFrame)


def environment_fingerprint() -> dict[str, object]:
    """Hardware/software the run executed on (published next to every measured number)."""
    cpu = platform.processor() or "unknown"
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
    except OSError:
        pass
    return {
        "cpu": cpu,
        "cpu_count": os.cpu_count(),
        "python": platform.python_version(),
        "pandas": metadata.version("pandas"),
        "postgres_driver": metadata.version("psycopg"),
        "environment": os.environ.get("RELUAI_ENVIRONMENT", "dev"),
    }


def create_run(
    db: Database, *, scenario: str, trigger: str, visitor_key: str | None = None
) -> uuid.UUID:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}")
    run_id = uuid.uuid4()
    with db.session() as s:
        s.add(
            PipelineRun(
                id=run_id,
                scenario=scenario,
                trigger=trigger,
                status="queued",
                simulated=SCENARIOS[scenario].simulated,
                visitor_key=visitor_key,
            )
        )
    return run_id


def resolve_drop(db: Database, drops: list[DropInfo], scenario: str) -> tuple[DropInfo, str]:
    """Pick the drop a scenario should process, with a human-readable reason."""
    by_key = {d.key: d for d in drops}
    with db.session() as s:
        loaded = {row.drop_key: row for row in s.scalars(select(SourceDrop))}
    if scenario == "replay" and loaded:
        latest = max(loaded.values(), key=lambda r: r.last_processed_at)
        return by_key[latest.drop_key], f"replaying {latest.drop_key} (already loaded)"
    for d in drops:
        if d.key not in loaded:
            if scenario == "replay":
                return d, "nothing loaded yet; loading the first drop instead of replaying"
            return d, "next unloaded drop"
    oldest = min(loaded.values(), key=lambda r: r.last_processed_at)
    return by_key[oldest.drop_key], (
        f"all {len(drops)} drops loaded; re-processing least recently processed "
        f"{oldest.drop_key} (expect 0 new rows)"
    )


def _month_end(drop_key: str) -> date:
    y, m = (int(x) for x in drop_key.split("-"))
    return date(y, m, calendar.monthrange(y, m)[1])


class RunExecutor:
    def __init__(
        self,
        db: Database,
        settings: PipelineSettings,
        run_id: uuid.UUID,
        scenario: str,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.db = db
        self.settings = settings
        self.run_id = run_id
        self.scenario = scenario
        self.rec = RunRecorder(db, run_id)
        self.state = RunState()
        self.make_client = client_factory or (
            lambda: httpx.Client(timeout=settings.crm_timeout_seconds)
        )

    # ------------------------------------------------------------------------- steps
    def resolve(self) -> DropInfo:
        with self.rec.step("resolve") as st:
            drop, note = resolve_drop(
                self.db, load_index(self.settings.sources_dir).drops, self.scenario
            )
            self.state.drop_key, self.state.note = drop.key, note
            st.detail = {"drop": drop.key, "file": drop.file, "note": note}
            self.rec.log("info", "drop.resolved", drop=drop.key, scenario=self.scenario, note=note)
        return drop

    def extract(self, drop: DropInfo) -> tuple[ParsedDrop, list[dict[str, str]], CrmResult]:
        with self.rec.step("extract") as st:
            data = read_drop_file(self.settings.sources_dir, drop.file)
            if self.scenario == "corrupt_drop":
                data, faults = corrupt_drop(data, seed=self.run_id.int % (2**31))
                st.detail["simulated_faults"] = faults
                self.rec.log("warning", "drop.corrupted", simulated=True, **faults)
            catalogue = read_catalogue(self.settings.sources_dir)
            s = self.settings
            with self.make_client() as client:
                crm = fetch_customers(
                    client,
                    base_url=s.crm_base_url,
                    as_of=_month_end(drop.key),
                    page_size=s.crm_page_size,
                    max_attempts=s.crm_max_attempts,
                    backoff_initial=s.crm_backoff_initial_seconds,
                    backoff_max=s.crm_backoff_max_seconds,
                    simulated_fault=SIMULATED_CRM_FAULTS.get(self.scenario),
                )
            self._log_source_events(crm.events)
            self.state.source_retries = crm.retries
            st.detail.update(
                {
                    "crm_pages": crm.pages,
                    "crm_attempts": crm.attempts,
                    "crm_retries": crm.retries,
                    "customers": len(crm.customers),
                    "products": len(catalogue),
                    "drop_bytes": len(data),
                }
            )
            parsed = parse_drop(data)
            st.rows_out = self.state.rows_read = parsed.rows_read
        self.state.checks.append(schema_check(True, "header matches the 8-column contract"))
        return parsed, catalogue, crm

    def validate(
        self, drop: DropInfo, parsed: ParsedDrop, catalogue: list[dict[str, str]], crm: CrmResult
    ) -> ValidationResult:
        with self.rec.step("validate") as st:
            refs = ReferenceData(
                catalogue={p["stock_code"]: p["description"] for p in catalogue},
                customers=set(crm.customers),
            )
            v = validate(parsed, period=pd.Period(drop.key, freq="M"), refs=refs)
            st.rows_in, st.rows_out = v.rows_read, len(v.accepted)
            st.detail = {
                "rejected": dict(v.reject_counts),
                "warnings": dict(v.warning_counts),
                "deduplicated": v.rows_deduplicated,
            }
            self.state.quarantine = v.quarantine
            self.state.rows_rejected, self.state.rows_warned = v.rows_rejected, v.rows_warned
            for code, n in v.reject_counts.most_common():
                self.rec.log("info", "rows.quarantined", reason=code, rows=n)
            if v.rows_deduplicated:
                self.rec.log("info", "rows.deduplicated", rows=v.rows_deduplicated)
        return v

    def transform(self, v: ValidationResult) -> Transformed:
        with self.rec.step("transform") as st:
            t = transform(v.accepted)
            st.rows_in, st.rows_out = len(v.accepted), len(t.lines)
            st.detail = {
                "invoices": len(t.invoices),
                "key_collisions": t.key_collisions,
                "line_types": {
                    str(k): int(n) for k, n in t.lines["line_type"].value_counts().items()
                },
            }
            self.state.rows_accepted = len(t.lines)
            self.state.rows_deduplicated = v.rows_deduplicated + t.key_collisions
        return t

    def quality_gate(self, v: ValidationResult) -> None:
        with self.rec.step("quality_gate") as st:
            self.state.checks.extend(batch_checks(v, self.settings))
            failed = [c for c in self.state.checks if c.severity == "gate" and not c.passed]
            st.detail = {"checks": len(self.state.checks), "failed_gates": [c.name for c in failed]}
            for chk in self.state.checks:
                self.rec.log(
                    "info" if chk.passed else "warning",
                    "dq.check",
                    check=chk.name,
                    passed=chk.passed,
                    observed=chk.observed,
                    threshold=chk.threshold,
                )
            _raise_if_gates_failed(failed)

    def load(
        self, drop: DropInfo, t: Transformed, crm: CrmResult, catalogue: list[dict[str, str]]
    ) -> None:
        with self.rec.step("load") as st, self.db.session() as s:
            previous = s.scalar(
                select(func.max(SourceDrop.drop_key)).where(SourceDrop.drop_key < drop.key)
            )
            already = s.get(SourceDrop, drop.key)
            result = load_batch(
                s,
                run_id=self.run_id,
                drop_key=drop.key,
                lines=t.lines,
                invoices=t.invoices,
                customers=crm.customers,
                catalogue=catalogue,
            )
            wh = warehouse_checks(
                s,
                drop_key=drop.key,
                expected_lines=len(t.lines),
                previous_drop=None if already else previous,
            )
            _raise_if_reconciliation_failed(wh)
            now = datetime.now(UTC)
            if already:
                already.times_processed += 1
                already.last_processed_at = now
            else:
                s.add(
                    SourceDrop(
                        drop_key=drop.key,
                        file_name=drop.file,
                        sha256=drop.sha256,
                        rows=drop.rows,
                        first_loaded_run_id=self.run_id,
                        first_loaded_at=now,
                        last_processed_at=now,
                    )
                )
            self.state.checks.extend(wh)
            st.rows_in, st.rows_out = len(t.lines), result.lines_inserted
            st.detail = {
                "lines_inserted": result.lines_inserted,
                "lines_unchanged": result.lines_unchanged,
                "invoices_inserted": result.invoices_inserted,
                "customers_upserted": result.customers_upserted,
                "products_upserted": result.products_upserted,
            }
            self.state.rows_inserted = result.lines_inserted
            self.state.rows_unchanged = result.lines_unchanged
        self.rec.log(
            "info",
            "run.published",
            drop=drop.key,
            inserted=self.state.rows_inserted,
            unchanged=self.state.rows_unchanged,
        )

    # --------------------------------------------------------------------- orchestration
    def execute(self) -> RunOutcome:
        t0 = time.perf_counter()
        step = "resolve"
        try:
            drop = self.resolve()
            step = "extract"
            parsed, catalogue, crm = self.extract(drop)
            step = "validate"
            v = self.validate(drop, parsed, catalogue, crm)
            step = "transform"
            t = self.transform(v)
            step = "quality_gate"
            self.quality_gate(v)
            step = "load"
            self.load(drop, t, crm, catalogue)
        except CrmUnavailableError as exc:
            self.state.source_retries = exc.retries
            self._log_source_events(exc.events)
            self._fail("extract", str(exc), "source_unavailable")
        except SchemaMismatchError as exc:
            self.state.checks.append(schema_check(False, str(exc)))
            self._fail("extract", str(exc), "schema_mismatch")
        except QualityGateError as exc:
            self.rec.skip("load", "quality gate failed; nothing published")
            self._fail("quality_gate", str(exc), "quality_gate")
        except ReconciliationError as exc:
            self._fail("load", str(exc), "reconciliation")
        except Exception as exc:
            log.exception("pipeline.unexpected_error", run_id=str(self.run_id), step=step)
            self._fail(
                step, f"internal error ({type(exc).__name__}); see service logs", "internal_error"
            )
        return self._finish(round((time.perf_counter() - t0) * 1000))

    # --------------------------------------------------------------------------- helpers
    def _log_source_events(self, events: list[dict[str, Any]]) -> None:
        for ev in events:
            fields = dict(ev)
            self.rec.log("warning", str(fields.pop("event")), **fields)

    def _fail(self, step: str, error: str, reason: str) -> None:
        self.state.status, self.state.failure_step, self.state.error = "failed", step, error
        self.rec.log("error", "run.failed", step=step, reason=reason, error=error)

    def _finish(self, duration_ms: int) -> RunOutcome:
        st = self.state
        score = dq_score(st.checks) if st.checks else None
        self.rec.log(
            "info", "run.finished", status=st.status, duration_ms=duration_ms, dq_score=score
        )
        self.rec.checkpoint()
        persist_results(
            self.db,
            self.settings,
            run_id=self.run_id,
            drop_key=st.drop_key,
            quarantine=st.quarantine,
            checks=st.checks,
        )
        with self.db.session() as s:
            s.execute(
                update(PipelineRun)
                .where(PipelineRun.id == self.run_id)
                .values(
                    status=st.status,
                    finished_at=datetime.now(UTC),
                    duration_ms=duration_ms,
                    drop_key=st.drop_key,
                    dq_score=score,
                    failure_step=st.failure_step,
                    error_message=st.error,
                    note=st.note,
                    rows_read=st.rows_read,
                    rows_accepted=st.rows_accepted,
                    rows_rejected=st.rows_rejected,
                    rows_deduplicated=st.rows_deduplicated,
                    rows_warned=st.rows_warned,
                    rows_inserted=st.rows_inserted,
                    rows_unchanged=st.rows_unchanged,
                    source_retries=st.source_retries,
                )
            )
        return RunOutcome(
            run_id=self.run_id,
            status=st.status,
            drop_key=st.drop_key,
            rows_read=st.rows_read,
            rows_inserted=st.rows_inserted,
            rows_rejected=st.rows_rejected,
            dq_score=score,
            failure_step=st.failure_step,
            duration_ms=duration_ms,
        )


def _raise_if_gates_failed(failed: list[CheckResult]) -> None:
    if failed:
        reasons = "; ".join(f"{c.detail} (limit {c.threshold})" for c in failed)
        raise QualityGateError(f"Nothing was published: {reasons}")


def _raise_if_reconciliation_failed(checks: list[CheckResult]) -> None:
    if not all(c.passed for c in checks if c.severity == "gate"):
        raise ReconciliationError("warehouse reconciliation failed")


def execute_run(
    db: Database,
    settings: PipelineSettings,
    run_id: uuid.UUID,
    *,
    client_factory: ClientFactory | None = None,
) -> RunOutcome:
    """Execute a queued run (the caller holds the CPU lease)."""
    with db.session() as s:
        run = s.get(PipelineRun, run_id)
        if run is None:
            raise LookupError(f"run {run_id} not found")
        scenario = run.scenario
        run.status = "running"
        run.started_at = datetime.now(UTC)
        run.environment = environment_fingerprint()
    return RunExecutor(db, settings, run_id, scenario, client_factory).execute()


def quarantine_sample(quarantine: pd.DataFrame, limit: int) -> pd.DataFrame:
    """At most ``limit`` rows, shared evenly across reasons so every reason keeps examples.

    A drop with tens of thousands of duplicates must not crowd out the 12 malformed rows
    someone actually wants to inspect.
    """
    if len(quarantine) <= limit:
        return quarantine
    per_reason = max(1, limit // max(1, quarantine["reason_code"].nunique()))
    return quarantine.groupby("reason_code", sort=False).head(per_reason)


def persist_results(
    db: Database,
    settings: PipelineSettings,
    *,
    run_id: uuid.UUID,
    drop_key: str | None,
    quarantine: pd.DataFrame,
    checks: list[CheckResult],
) -> None:
    with db.session() as s:
        if drop_key is not None and len(quarantine):
            rows = quarantine_sample(quarantine, settings.quarantine_store_limit)
            s.execute(
                insert(QuarantinedRow),
                [
                    {
                        "run_id": run_id,
                        "drop_key": drop_key,
                        "line_number": int(r["line_number"]),
                        "reason_code": str(r["reason_code"]),
                        "severity": str(r["severity"]),
                        "raw": r["raw"],
                    }
                    for r in rows.to_dict(orient="records")
                ],
            )
        if checks:
            s.execute(
                insert(DqResult),
                [
                    {
                        "run_id": run_id,
                        "check_name": c.name,
                        "dimension": c.dimension,
                        "stage": c.stage,
                        "severity": c.severity,
                        "passed": c.passed,
                        "observed": c.observed,
                        "threshold": c.threshold,
                        "weight": c.weight,
                        "detail": c.detail,
                    }
                    for c in checks
                ],
            )
