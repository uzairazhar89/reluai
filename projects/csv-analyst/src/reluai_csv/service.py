"""Answering a question: interpret (rules, then optionally an LLM), validate, compile, run."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from reluai_core.db import Database
from reluai_core.logging import get_logger
from reluai_csv import datasets
from reluai_csv.compile import compile_plan
from reluai_csv.datasets import BUNDLED_EXAMPLES, BUNDLED_ID, UploadStore
from reluai_csv.llm import plan_with_llm
from reluai_csv.models import QueryLog
from reluai_csv.parser import parse_question
from reluai_csv.plan import QueryPlan
from reluai_csv.profile import Profile
from reluai_csv.sandbox import QueryFailedError, QueryTimeoutError, run_query
from reluai_csv.schema import DatasetSchema
from reluai_csv.schemas import (
    AskRequest,
    AskResponse,
    AttemptOut,
    ColumnOut,
    DatasetOut,
    FindingOut,
    InterpreterOut,
    ResultColumn,
    Timings,
    UsageOut,
    ValueCount,
)
from reluai_csv.settings import CsvSettings
from reluai_csv.validate import validate_plan
from reluai_inference.chain import ProviderChain

log = get_logger(__name__)
BUNDLED_TITLE = "Online retailer invoice lines, December 2009 to December 2011"
BUNDLED_PROVENANCE = "Real data: UCI Online Retail II (CC BY 4.0)"
UPLOAD_PROVENANCE = "Your upload: kept in memory-backed storage and deleted after one hour"


@dataclass(frozen=True, slots=True)
class Target:
    id: str
    kind: str  # bundled | upload
    title: str
    path: Path
    profile: Profile
    schema: DatasetSchema
    expires_at: float | None = None

    @property
    def examples(self) -> list[str]:
        return list(BUNDLED_EXAMPLES) if self.kind == "bundled" else suggest_examples(self.schema)


def resolve(dataset: str, settings: CsvSettings, store: UploadStore) -> Target | None:
    if dataset == BUNDLED_ID:
        profile = datasets.bundled_profile(settings)
        return Target(
            id=BUNDLED_ID,
            kind="bundled",
            title=BUNDLED_TITLE,
            path=settings.bundled_db,
            profile=profile,
            schema=datasets.bundled_schema(settings),
        )
    upload = store.get(dataset)
    if upload is None:
        return None
    return Target(
        id=upload.id,
        kind="upload",
        title=upload.label,
        path=upload.path,
        profile=upload.profile,
        schema=upload.schema(),
        expires_at=upload.expires_at,
    )


def suggest_examples(schema: DatasetSchema) -> list[str]:
    """Questions the rules can answer for an uploaded table, built from its columns."""
    cats = [
        c for c in schema.columns if c.kind == "text" and c.distinct is not None and c.distinct > 1
    ]
    nums = [c for c in schema.columns if c.numeric and not c.entity]
    out = [f"How many {schema.row_noun}?"]
    if nums:
        agg = "Total" if nums[0].additive else "Average"
        out.append(f"{agg} {nums[0].label}")
    if nums and cats:
        out.append(f"{nums[0].label.capitalize()} by {cats[0].label}")
    if cats:
        out.append(f"Most common {cats[0].label}")
    if nums and schema.default_date:
        out.append(f"{nums[0].label.capitalize()} per month")
    if len(nums) > 1 and cats:
        out.append(f"Average {nums[1].label} by {cats[0].label}")
    return out[:6]


def dataset_out(target: Target, *, llm_available: bool = False) -> DatasetOut:
    meta = {c.name: c for c in target.schema.columns}
    return DatasetOut(
        id=target.id,
        kind="bundled" if target.kind == "bundled" else "upload",
        title=target.title,
        table=target.schema.table,
        rows=target.profile.rows,
        duplicate_rows=target.profile.duplicate_rows,
        columns=[
            ColumnOut(
                name=c.name,
                kind=c.kind,
                sql_type=c.sql_type,
                description=meta[c.name].description if c.name in meta else "",
                non_null=c.non_null,
                nulls=c.nulls,
                distinct=c.distinct,
                min=c.min,
                max=c.max,
                # The average of an ID column (customer numbers) means nothing.
                mean=None if c.name in meta and meta[c.name].entity else c.mean,
                top_values=[ValueCount(value=v, count=n) for v, n in c.top_values],
            )
            for c in target.profile.columns
        ],
        findings=[
            FindingOut(
                severity=f.severity,
                code=f.code,
                message=f.message,
                column=f.column,
                count=f.count,
            )
            for f in target.profile.findings
        ],
        provenance=BUNDLED_PROVENANCE if target.kind == "bundled" else UPLOAD_PROVENANCE,
        examples=target.examples,
        expires_at=datetime.fromtimestamp(target.expires_at, UTC) if target.expires_at else None,
        llm_available=llm_available,
    )


def ask(  # noqa: PLR0912
    request: AskRequest,
    target: Target,
    *,
    settings: CsvSettings,
    db: Database | None,
    visitor: str | None,
    chain_factory: Callable[[], ProviderChain] | None,
) -> AskResponse:
    t0 = time.perf_counter()
    question = " ".join(request.question.split())
    schema = target.schema
    interpreter = InterpreterOut(kind="none")
    plan: QueryPlan | None = None
    status = "not_understood"
    message: str | None = None
    issues: list[str] = []

    parsed = parse_question(question, schema)
    if parsed.plan is not None:
        checked = validate_plan(parsed.plan, schema)
        if checked.ok and checked.plan is not None:
            plan = checked.plan
            interpreter = InterpreterOut(kind="rules", pattern=parsed.pattern)
        else:  # the rules produced something the validator rejects: a bug, never shown as data
            log.warning("csv.rules_plan_invalid", codes=[i.code for i in checked.issues])
    interpret_ms = (time.perf_counter() - t0) * 1000

    if plan is None:
        llm_allowed = target.kind == "bundled" or request.allow_llm
        if not llm_allowed:
            message = (
                "The rule-based interpreter could not read this question. Rephrase it, try "
                "one of the suggestions, or allow the LLM fallback for this upload."
            )
        elif chain_factory is None:
            message = "The rule-based interpreter could not read this question."
        else:
            t1 = time.perf_counter()
            r = plan_with_llm(
                question,
                schema,
                rows=target.profile.rows,
                include_values=target.kind == "bundled",
                chain_factory=chain_factory,
                visitor=visitor,
                max_retries=settings.llm_max_retries,
            )
            interpret_ms += (time.perf_counter() - t1) * 1000
            interpreter = InterpreterOut(
                kind="llm" if r.provider else "none",
                provider=r.provider,
                model=r.model,
                retries=r.retries,
                tokens=r.tokens,
                latency_ms=r.latency_ms,
                attempts=[
                    AttemptOut(
                        provider=a.provider,
                        model=a.model,
                        outcome=a.outcome,
                        latency_ms=a.latency_ms,
                    )
                    for a in r.attempts
                ],
            )
            if r.plan is not None:
                plan = r.plan
            elif r.refusal:
                status, message = "refused", r.refusal
            elif r.unavailable:
                message = (
                    "The rule-based interpreter could not read this question, and no language "
                    "model is available on this server right now. Try rephrasing it, or one "
                    "of the suggestions."
                )
            else:
                message = (
                    f"The language model did not produce a valid query plan in "
                    f"{r.retries + 1} attempts, so nothing was run."
                )
                issues = [i.message for i in r.issues]

    if plan is None:
        response = AskResponse(
            status=status,  # type: ignore[arg-type]
            question=question,
            message=message,
            interpreter=interpreter,
            timings=Timings(
                interpret_ms=round(interpret_ms, 1),
                query_ms=0,
                total_ms=round((time.perf_counter() - t0) * 1000, 1),
            ),
            suggestions=target.examples,
            issues=issues,
        )
        _record(db, target, response, error_code=None)
        return response

    compiled = compile_plan(plan, schema)
    try:
        result = run_query(
            target.path, compiled.sql, compiled.params, settings, max_rows=plan.limit
        )
    except (QueryTimeoutError, QueryFailedError) as exc:
        timeout = isinstance(exc, QueryTimeoutError)
        response = AskResponse(
            status="failed",
            question=question,
            message=(
                f"The query was stopped after {settings.query_timeout_seconds:g} seconds."
                if timeout
                else "The database could not run this query."
            ),
            interpreter=interpreter,
            plan=plan,
            summary=compiled.summary,
            sql=compiled.display_sql,
            pandas=compiled.pandas,
            timings=Timings(
                interpret_ms=round(interpret_ms, 1),
                query_ms=0,
                total_ms=round((time.perf_counter() - t0) * 1000, 1),
            ),
        )
        _record(db, target, response, error_code="timeout" if timeout else "query_failed")
        return response

    response = AskResponse(
        status="answered",
        question=question,
        interpreter=interpreter,
        plan=plan,
        summary=compiled.summary,
        sql=compiled.display_sql,
        pandas=compiled.pandas,
        columns=[
            ResultColumn(name=c.name, role=c.role, kind=c.kind, label=c.label)  # type: ignore[arg-type]
            for c in compiled.columns
        ],
        rows=result.rows,
        truncated=result.truncated,
        chart=compiled.chart,
        timings=Timings(
            interpret_ms=round(interpret_ms, 1),
            query_ms=result.elapsed_ms,
            total_ms=round((time.perf_counter() - t0) * 1000, 1),
        ),
    )
    _record(db, target, response, error_code=None)
    return response


def _record(db: Database | None, target: Target, r: AskResponse, *, error_code: str | None) -> None:
    if db is None:
        return
    try:
        with db.session() as s:
            s.add(
                QueryLog(
                    dataset_kind="bundled" if target.kind == "bundled" else "upload",
                    status=r.status,
                    interpreter=r.interpreter.kind,
                    pattern=(r.interpreter.pattern or "")[:40] or None,
                    provider=r.interpreter.provider,
                    retries=r.interpreter.retries,
                    tokens=r.interpreter.tokens,
                    result_rows=len(r.rows),
                    interpret_ms=r.timings.interpret_ms,
                    query_ms=r.timings.query_ms,
                    error_code=error_code,
                )
            )
    except Exception:
        log.exception("csv.query_log_failed")


def usage(db: Database, days: int = 30) -> UsageOut:
    since = datetime.now(UTC) - timedelta(days=days)
    with db.session() as s:
        rows = s.execute(
            select(QueryLog.status, QueryLog.interpreter, func.count(), func.sum(QueryLog.retries))
            .where(QueryLog.ts >= since)
            .group_by(QueryLog.status, QueryLog.interpreter)
        ).all()
    counts: dict[tuple[str, str], int] = {(st, it): int(n) for st, it, n, _ in rows}
    retries = sum(int(r or 0) for *_, r in rows)
    return UsageOut(
        questions=sum(counts.values()),
        answered_by_rules=counts.get(("answered", "rules"), 0),
        answered_by_llm=counts.get(("answered", "llm"), 0),
        not_understood=sum(n for (st, _), n in counts.items() if st == "not_understood"),
        refused=sum(n for (st, _), n in counts.items() if st == "refused"),
        llm_retries=retries,
    )


def answer_with_rules(question: str, settings: CsvSettings) -> dict[str, Any]:
    """CLI helper: rules only, bundled table, nothing recorded."""
    store = UploadStore(settings)
    target = resolve(BUNDLED_ID, settings, store)
    assert target is not None  # noqa: S101
    response = ask(
        AskRequest(dataset=BUNDLED_ID, question=question),
        target,
        settings=settings,
        db=None,
        visitor=None,
        chain_factory=None,
    )
    return response.model_dump(mode="json")
