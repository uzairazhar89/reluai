"""Invoice extraction routes (mounted at ``/api/documents/invoices``)."""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, File, Path, Request, Response, UploadFile

from reluai_core.cpu_lease import LeaseUnavailableError
from reluai_core.db import Database, DatabaseDep
from reluai_core.errors import ProblemError
from reluai_core.http import client_ip
from reluai_core.ratelimit import consume_quota, visitor_key
from reluai_docs.invoices import service
from reluai_docs.pdfread import ReadError
from reluai_docs.schemas import InvoiceEvaluationOut, InvoiceGalleryOut, InvoiceRunOut
from reluai_docs.settings import DocsSettings, get_docs_settings

router = APIRouter(prefix="/invoices", tags=["documents"])
SettingsDep = Annotated[DocsSettings, Depends(get_docs_settings)]
DocId = Annotated[str, Path(pattern=r"^C?\d{6}-s\d{1,4}(-scan)?$", max_length=24)]


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


def _problem(exc: Exception) -> ProblemError:
    if isinstance(exc, service.InvoiceError):
        return ProblemError(exc.status, exc.message, code=exc.code)
    if isinstance(exc, ReadError):
        return ProblemError(422, exc.message, code=exc.code)
    return ProblemError(
        503,
        "The server is busy with other work; try again in a minute.",
        code="busy",
        headers={"Retry-After": "30"},
    )


@router.get("", response_model=InvoiceGalleryOut)
def get_gallery(db: DatabaseDep, settings: SettingsDep) -> InvoiceGalleryOut:
    """The sample invoices (real records drawn in generated layouts, some as scans), with
    each one's outcome in the latest evaluation run."""
    return service.gallery(db, settings)


@router.get("/evaluation", response_model=InvoiceEvaluationOut | None)
def get_evaluation(db: DatabaseDep) -> InvoiceEvaluationOut | None:
    """The latest extraction evaluation run (accuracy against the records), if any."""
    run = service.latest_run(db)
    return service.evaluation_out(run) if run else None


@router.get(
    "/{doc_id}.pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def get_pdf(doc_id: DocId, settings: SettingsDep) -> Response:
    """The sample invoice as a PDF (generated on request, the same bytes every time)."""
    try:
        pdf = service.sample_pdf(settings, doc_id)
    except service.InvoiceError as exc:
        raise _problem(exc) from exc
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="invoice-{doc_id}.pdf"',
            "Cache-Control": "public, max-age=86400",
        },
    )


@router.post("/{doc_id}/extract", response_model=InvoiceRunOut)
def post_extract(
    doc_id: DocId, request: Request, db: DatabaseDep, settings: SettingsDep
) -> InvoiceRunOut:
    """Read a sample invoice now, as an upload would be read, and compare every value with
    the record it was drawn from."""
    _quota(db, f"docs:invoice:{_visitor(request)}", settings.visitor_invoice_runs_per_hour,
           "invoice extractions")  # fmt: skip
    try:
        return service.run_sample(db, settings, doc_id)
    except (service.InvoiceError, ReadError, LeaseUnavailableError) as exc:
        raise _problem(exc) from exc


@router.post("/uploads", response_model=InvoiceRunOut)
def post_upload(
    request: Request,
    db: DatabaseDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="PDF invoice, up to 10 MB")],
) -> InvoiceRunOut:
    """Read your own invoice PDF. Nothing is stored: the file is read in memory, in an
    isolated process, and only the result is returned. With no record to compare against,
    the checks are the only verdict."""
    _quota(db, f"docs:upload:{_visitor(request)}", settings.visitor_uploads_per_hour, "uploads")
    data = file.file.read(settings.upload_max_bytes + 1)
    name = re.sub(r"[^\w.\- ]+", "_", (file.filename or "invoice.pdf"))[:120]
    try:
        return service.run_upload(db, settings, data, name)
    except (service.InvoiceError, ReadError, LeaseUnavailableError) as exc:
        raise _problem(exc) from exc
