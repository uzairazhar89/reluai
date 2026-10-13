"""Public API of Document Intelligence (mounted at ``/api/documents``)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile, status
from sqlalchemy import select

from reluai_core.db import Database, DatabaseDep
from reluai_core.errors import ProblemError
from reluai_core.http import client_ip
from reluai_core.logging import get_logger
from reluai_core.ratelimit import consume_quota, visitor_key
from reluai_docs import service
from reluai_docs.embedding import TextEmbedder
from reluai_docs.models import DocumentRecord, EvaluationRun
from reluai_docs.schemas import (
    AnswerOut,
    ChunksOut,
    DocumentOut,
    QaEvaluationItemOut,
    QaEvaluationRunOut,
    QuestionRequest,
)
from reluai_docs.settings import DocsSettings, get_docs_settings
from reluai_inference.chain import ProviderChain
from reluai_inference.config import build_chain, configured_providers, get_inference_settings

router = APIRouter(tags=["documents"])
log = get_logger(__name__)
SettingsDep = Annotated[DocsSettings, Depends(get_docs_settings)]
HOSTED = ("groq", "cerebras")


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


def _chain_factory(request: Request, db: Database) -> service.ChainFactory:
    override: service.ChainFactory | None = getattr(request.app.state, "docs_chain_factory", None)
    if override is not None:
        return override

    def make(external: bool) -> ProviderChain | None:
        chain = build_chain(get_inference_settings(), db, role="answer")
        providers = [
            p for p in chain.providers if p.available() and (external or p.name not in HOSTED)
        ]
        return ProviderChain(providers, chain.ledger) if providers else None

    return make


def _llm_flags(request: Request) -> tuple[bool, bool]:
    override: service.ChainFactory | None = getattr(request.app.state, "docs_chain_factory", None)
    if override is not None:
        hosted, local = override(True), override(False)
        return hosted is not None or local is not None, hosted is not None
    names = configured_providers(get_inference_settings())
    return bool(names), any(n in HOSTED for n in names)


def _embedder(request: Request, settings: DocsSettings) -> service.EmbedderLoader:
    override: Callable[[], TextEmbedder | None] | None = getattr(
        request.app.state, "docs_embedder", None
    )
    return override or service.default_embedder(settings)


def _out(request: Request, rec: DocumentRecord) -> DocumentOut:
    llm, external = _llm_flags(request)
    return service.document_out(rec, llm=llm, external_llm=external)


def _record(
    db: Database, doc_id: uuid.UUID, request: Request, settings: DocsSettings
) -> DocumentRecord:
    if doc_id == service.SAMPLE_ID:
        rec = service.ensure_sample(db, settings)
        if rec is None:
            raise ProblemError(
                503, "The sample document is not installed here.", code="sample_unavailable"
            )
        return rec
    try:
        return service.get_record(db, doc_id, visitor=_visitor(request))
    except service.DocumentError as exc:
        raise ProblemError(exc.status, exc.message, code=exc.code) from exc


def _defer(request: Request, doc_id: uuid.UUID) -> None:
    override: Callable[[uuid.UUID], None] | None = getattr(request.app.state, "docs_deferrer", None)
    if override is not None:
        override(doc_id)
        return
    request.app.state.jobs.configure_task("docs:process_document", priority=10).defer(
        document_id=str(doc_id)
    )


@router.get("/sample", response_model=DocumentOut)
def get_sample(request: Request, db: DatabaseDep, settings: SettingsDep) -> DocumentOut:
    """The bundled sample document (NIST AI RMF 1.0), ready for questions."""
    return _out(request, _record(db, service.SAMPLE_ID, request, settings))


@router.post("/uploads", response_model=DocumentOut, status_code=status.HTTP_202_ACCEPTED)
def post_upload(
    request: Request,
    db: DatabaseDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="PDF, up to 10 MB")],
) -> DocumentOut:
    """Queue a PDF for reading. Poll ``GET /{id}`` until ``status`` is ready or failed.

    The file is held in memory until the worker reads it, then discarded; the extracted text
    is deleted after an hour. Neither is logged.
    """
    if service.pending(db) >= settings.max_pending:
        raise ProblemError(
            503,
            "Several documents are being read right now; try again in a minute.",
            code="busy",
            headers={"Retry-After": "30"},
        )
    visitor = _visitor(request)
    _quota(db, f"docs:upload:{visitor}", settings.visitor_uploads_per_hour, "uploads")
    data = file.file.read(settings.upload_max_bytes + 1)
    try:
        rec = service.create_upload(
            db, settings, visitor=visitor, data=data, filename=file.filename
        )
    except service.DocumentError as exc:
        raise ProblemError(exc.status, exc.message, code=exc.code) from exc
    try:
        _defer(request, rec.id)
    except Exception as exc:
        log.exception("docs.defer_failed", document=rec.id.hex[:8])
        with db.session() as s:
            service._drop(s, rec.id)
        (settings.spool_dir / f"{rec.id.hex}.pdf").unlink(missing_ok=True)
        raise ProblemError(503, "The document queue is unavailable.", code="queue_down") from exc
    return _out(request, service.get_record(db, rec.id, visitor=visitor))


@router.get("/evaluation", response_model=list[QaEvaluationRunOut])
def get_evaluation(db: DatabaseDep) -> list[QaEvaluationRunOut]:
    """The latest evaluation run per answering method, on the sample document."""
    with db.session() as s:
        rows = s.scalars(select(EvaluationRun).order_by(EvaluationRun.ran_at.desc())).all()
        latest: dict[str, EvaluationRun] = {}
        for r in rows:
            latest.setdefault(r.label, r)
        return [
            QaEvaluationRunOut(
                label=r.label,
                ran_at=r.ran_at,
                document=r.document,
                questions=r.questions,
                correct=r.correct,
                tokens=r.tokens,
                median_latency_ms=r.median_latency_ms,
                p95_latency_ms=r.p95_latency_ms,
                metrics=r.metrics,
                environment=r.environment,
                results=[QaEvaluationItemOut.model_validate(x) for x in r.results],
            )
            for r in sorted(latest.values(), key=lambda r: r.label)
        ]


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(
    document_id: uuid.UUID, request: Request, db: DatabaseDep, settings: SettingsDep
) -> DocumentOut:
    """Processing status, page counts, outline and warnings."""
    return _out(request, _record(db, document_id, request, settings))


@router.get("/{document_id}/chunks", response_model=ChunksOut)
def get_chunks(
    document_id: uuid.UUID,
    *,
    request: Request,
    db: DatabaseDep,
    settings: SettingsDep,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> ChunksOut:
    """The passages the document was split into, as they are searched."""
    rec = _record(db, document_id, request, settings)
    return service.chunks(db, rec, offset=offset, limit=limit)


@router.post("/{document_id}/ask", response_model=AnswerOut)
def post_ask(
    document_id: uuid.UUID,
    body: QuestionRequest,
    *,
    request: Request,
    db: DatabaseDep,
    settings: SettingsDep,
) -> AnswerOut:
    """Answer a question from this document only, citing page-numbered passages."""
    visitor = _visitor(request)
    rec = _record(db, document_id, request, settings)
    _quota(db, f"docs:ask:{visitor}", settings.visitor_questions_per_hour, "questions")
    try:
        return service.ask(
            db,
            settings,
            rec,
            body,
            visitor=visitor,
            chain_factory=_chain_factory(request, db),
            embedder=_embedder(request, settings),
        )
    except service.DocumentError as exc:
        raise ProblemError(exc.status, exc.message, code=exc.code) from exc


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def delete_document(
    document_id: uuid.UUID, request: Request, db: DatabaseDep, settings: SettingsDep
) -> Response:
    """Delete an uploaded document and its passages now, rather than after an hour."""
    rec = _record(db, document_id, request, settings)
    try:
        service.delete_document(db, settings, rec)
    except service.DocumentError as exc:
        raise ProblemError(exc.status, exc.message, code=exc.code) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
