"""Public API of the AI CSV Analyst (mounted at ``/api/csv``)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status
from sqlalchemy import select

from reluai_core.db import Database, DatabaseDep
from reluai_core.errors import ProblemError
from reluai_core.http import client_ip
from reluai_core.logging import get_logger
from reluai_core.ratelimit import consume_quota, visitor_key
from reluai_csv import service
from reluai_csv.datasets import BUNDLED_ID, UploadRejectedError, UploadStore
from reluai_csv.models import EvaluationRun
from reluai_csv.sandbox import SandboxBusyError
from reluai_csv.schemas import (
    AskRequest,
    AskResponse,
    DatasetOut,
    EvaluationItem,
    EvaluationOut,
    EvaluationSet,
    UsageOut,
)
from reluai_csv.settings import CsvSettings, get_csv_settings
from reluai_inference.chain import ProviderChain
from reluai_inference.config import build_chain, configured_providers, get_inference_settings

router = APIRouter(tags=["csv"])
log = get_logger(__name__)
SettingsDep = Annotated[CsvSettings, Depends(get_csv_settings)]
ChainFactory = Callable[[], ProviderChain]


def _visitor(request: Request) -> str:
    secret = request.app.state.core_settings.visitor_hash_secret.get_secret_value()
    return visitor_key(client_ip(request), secret)


def _quota(db: Database, key: str, limit: int, what: str) -> None:
    with db.session() as s:
        result = consume_quota(s, key=key, limit=limit, window=timedelta(hours=1))
    if not result.allowed:
        raise ProblemError(
            429,
            f"Limit of {limit} {what} per hour reached; try again later.",
            code="quota_exceeded",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


def _chain_factory(request: Request, db: Database) -> ChainFactory:
    override: ChainFactory | None = getattr(request.app.state, "csv_chain_factory", None)
    if override is not None:
        return override
    return lambda: build_chain(get_inference_settings(), db, role="fast")


def _llm_available(request: Request) -> bool:
    override: ChainFactory | None = getattr(request.app.state, "csv_chain_factory", None)
    if override is not None:
        return any(p.available() for p in override().providers)
    return bool(configured_providers(get_inference_settings()))


def _target(dataset: str, settings: CsvSettings) -> service.Target:
    try:
        target = service.resolve(dataset, settings, UploadStore(settings))
    except FileNotFoundError as exc:
        raise ProblemError(
            503, "The bundled dataset is not available on this server.", code="dataset_unavailable"
        ) from exc
    if target is None:
        raise ProblemError(
            404,
            "This upload has expired or does not exist. Uploads are deleted after one hour; "
            "upload the file again.",
            code="upload_not_found",
        )
    return target


@router.get("/datasets/retail", response_model=DatasetOut)
def get_bundled(request: Request, settings: SettingsDep) -> DatasetOut:
    """The bundled real retailer table: columns, profile and data-quality findings."""
    return service.dataset_out(_target(BUNDLED_ID, settings), llm_available=_llm_available(request))


@router.post("/uploads", response_model=DatasetOut, status_code=status.HTTP_201_CREATED)
def post_upload(
    request: Request,
    db: DatabaseDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="CSV file, up to 2 MB and 50,000 rows")],
) -> DatasetOut:
    """Profile an uploaded CSV. It is stored for one hour and its contents are never logged."""
    _quota(db, f"csv:upload:{_visitor(request)}", settings.visitor_uploads_per_hour, "uploads")
    data = file.file.read(settings.upload_max_bytes + 1)
    try:
        upload = UploadStore(settings).save(data, file.filename)
    except UploadRejectedError as exc:
        raise ProblemError(422, exc.message, code=exc.code) from exc
    return service.dataset_out(_target(upload.id, settings), llm_available=_llm_available(request))


@router.get("/uploads/{upload_id}", response_model=DatasetOut)
def get_upload(upload_id: str, request: Request, settings: SettingsDep) -> DatasetOut:
    if not (len(upload_id) == 32 and all(ch in "0123456789abcdef" for ch in upload_id)):
        raise ProblemError(404, "Upload not found.", code="upload_not_found")
    return service.dataset_out(_target(upload_id, settings), llm_available=_llm_available(request))


@router.post("/ask", response_model=AskResponse)
def post_ask(
    body: AskRequest, request: Request, db: DatabaseDep, settings: SettingsDep
) -> AskResponse:
    """Interpret a question (rules first, then an optional LLM tool call) and answer it."""
    visitor = _visitor(request)
    _quota(db, f"csv:ask:{visitor}", settings.visitor_asks_per_hour, "questions")
    UploadStore(settings).purge()
    target = _target(body.dataset, settings)
    try:
        return service.ask(
            body,
            target,
            settings=settings,
            db=db,
            visitor=visitor,
            chain_factory=_chain_factory(request, db),
        )
    except SandboxBusyError as exc:
        raise ProblemError(
            503,
            "The analyst is busy with another query; try again in a few seconds.",
            code="busy",
            headers={"Retry-After": "5"},
        ) from exc


@router.get("/evaluation", response_model=EvaluationOut)
def get_evaluation(db: DatabaseDep) -> EvaluationOut:
    """The latest run of the fixed question sets (development and held-out)."""
    with db.session() as s:
        run = s.scalars(
            select(EvaluationRun).order_by(EvaluationRun.ran_at.desc()).limit(1)
        ).first()
    if run is None:
        raise ProblemError(404, "No evaluation has run yet.", code="no_evaluation")
    answerable = run.questions - run.declined_expected
    return EvaluationOut(
        ran_at=run.ran_at,
        development=EvaluationSet(
            questions=run.questions,
            correct=run.correct,
            wrong=run.wrong,
            declined_expected=run.declined_expected,
            declined_unexpected=run.declined_unexpected,
            accuracy=round(run.correct / answerable, 4) if answerable else 0.0,
        ),
        held_out=EvaluationSet.model_validate(run.held_out),
        query_p50_ms=run.query_p50_ms,
        query_p95_ms=run.query_p95_ms,
        environment=run.environment,
        items=[EvaluationItem.model_validate(i) for i in run.items],
    )


@router.get("/usage", response_model=UsageOut)
def get_usage(db: DatabaseDep) -> UsageOut:
    """How visitors' questions were handled over the last 30 days (no question text kept)."""
    return service.usage(db)
