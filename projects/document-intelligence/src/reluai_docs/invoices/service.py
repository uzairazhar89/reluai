"""Invoice extraction for the API: the gallery, live runs and the evaluation record.

A live run reads the PDF exactly as an upload would be read: in the isolated reader process
(segments and page previews requested), under the global CPU lease because a scan means
OCR. It is synchronous: an invoice is a few pages, and the lease wait is short, so a busy
server answers "try again" rather than queueing a visitor's request.
"""

from __future__ import annotations

import os
import platform
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select

from reluai_core.cpu_lease import cpu_lease
from reluai_core.db import Database
from reluai_core.logging import get_logger
from reluai_docs.invoices.evaluate import (
    DocumentResult,
    field_report,
    run_documents,
    summarise_run,
)
from reluai_docs.invoices.extract import extract_invoice
from reluai_docs.invoices.records import EvalDocument, load_set
from reluai_docs.invoices.render import document_pdf
from reluai_docs.isolation import ReaderLimits, read_isolated
from reluai_docs.models import InvoiceEvaluationRun
from reluai_docs.pdfread import ReadLimits, ReadResult
from reluai_docs.schemas import (
    InvoiceComparisonOut,
    InvoiceDocumentOut,
    InvoiceEvaluationItemOut,
    InvoiceEvaluationOut,
    InvoiceExtractionOut,
    InvoiceGalleryOut,
    InvoicePageOut,
    InvoiceRunOut,
)
from reluai_docs.settings import DocsSettings

log = get_logger(__name__)


class InvoiceError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# --------------------------------------------------------------------------- the set
@lru_cache(maxsize=2)
def _set(path: Path, mtime: float) -> tuple[EvalDocument, ...]:
    return tuple(load_set(path))


def documents(settings: DocsSettings) -> tuple[EvalDocument, ...]:
    path = settings.invoices_path
    try:
        return _set(path, path.stat().st_mtime)
    except FileNotFoundError:
        return ()


def find(settings: DocsSettings, doc_id: str) -> EvalDocument:
    for doc in documents(settings):
        if doc.id == doc_id:
            return doc
    raise InvoiceError(404, "invoice_not_found", "There is no sample invoice with this id.")


@lru_cache(maxsize=24)
def _pdf(doc: EvalDocument) -> bytes:
    return document_pdf(doc)


def sample_pdf(settings: DocsSettings, doc_id: str) -> bytes:
    return _pdf(find(settings, doc_id))


def _document_out(doc: EvalDocument, last: dict[str, str] | None = None) -> InvoiceDocumentOut:
    return InvoiceDocumentOut(
        id=doc.id,
        number=doc.invoice.number,
        split=doc.split,
        style=doc.style,
        scanned=doc.scanned,
        lines=len(doc.invoice.lines),
        credit_note=doc.invoice.credit_note,
        last_run=last.get(doc.id) if last else None,  # type: ignore[arg-type]
    )


# --------------------------------------------------------------------------- evaluation
def latest_run(db: Database) -> InvoiceEvaluationRun | None:
    with db.session() as s:
        return s.scalars(
            select(InvoiceEvaluationRun).order_by(InvoiceEvaluationRun.ran_at.desc()).limit(1)
        ).first()


def evaluation_out(run: InvoiceEvaluationRun) -> InvoiceEvaluationOut:
    return InvoiceEvaluationOut(
        ran_at=run.ran_at,
        documents=run.documents,
        exact=run.exact,
        median_ms=run.median_ms,
        metrics=run.metrics,
        environment=run.environment,
        results=[InvoiceEvaluationItemOut.model_validate(r) for r in run.results],
    )


def gallery(db: Database, settings: DocsSettings) -> InvoiceGalleryOut:
    run = latest_run(db)
    last: dict[str, str] = {}
    if run is not None:
        for r in run.results:
            last[r["id"]] = (
                "exact" if r["exact"] and not r["needs_review"]
                else "flagged" if r["needs_review"]
                else "wrong"
            )  # fmt: skip
    return InvoiceGalleryOut(
        documents=[_document_out(d, last) for d in documents(settings)],
        evaluated_at=run.ran_at if run else None,
    )


def evaluate(settings: DocsSettings, *, isolated: bool = True) -> list[DocumentResult]:
    """Extract every invoice of the set and compare with the records. Each document is
    read by the isolated reader, as a visitor's would be (``isolated=False`` reads in
    this process, which is faster for development)."""
    docs = list(documents(settings))
    if not docs:
        return []
    limits = _limits(settings, previews=False)
    return run_documents(docs, read=(lambda pdf: read_isolated(pdf, limits)) if isolated else None)


def environment() -> dict[str, str | int | float | None]:
    return {
        "python": platform.python_version(),
        "machine": platform.machine(),
        "cpus": os.cpu_count(),
        "reader": "isolated process, as for uploads",
    }


def record_run(db: Database, results: list[DocumentResult]) -> InvoiceEvaluationRun:
    metrics = summarise_run(results)
    run = InvoiceEvaluationRun(
        documents=len(results),
        exact=sum(1 for r in results if r.comparison.exact),
        median_ms=int(metrics["all"]["median_ms"]),
        metrics=metrics,
        environment=environment(),
        results=[r.to_json() for r in results],
    )
    with db.session() as s:
        s.add(run)
        s.flush()
        s.refresh(run)
        s.expunge(run)
    return run


# --------------------------------------------------------------------------- live runs
def _limits(settings: DocsSettings, *, previews: bool = True) -> ReaderLimits:
    return ReaderLimits(
        ReadLimits(
            max_pages=settings.invoice_max_pages,
            max_ocr_pages=settings.invoice_max_ocr_pages,
            ocr_dpi=settings.ocr_dpi,
            ocr_max_pixels=settings.ocr_max_pixels,
            ocr_threads=settings.embed_threads,
            segments=True,
            preview_pages=settings.invoice_max_pages if previews else 0,
            preview_dpi=settings.invoice_preview_dpi,
        ),
        timeout_seconds=settings.read_timeout_seconds,
        cpu_seconds=settings.read_cpu_seconds,
        memory_mb=settings.read_memory_mb,
        max_bytes=settings.upload_max_bytes,
    )


def _read(
    db: Database, settings: DocsSettings, data: bytes, holder: str
) -> tuple[ReadResult, dict[str, int]]:
    t_wait = time.perf_counter()
    with cpu_lease(db.engine, holder=holder, wait_seconds=settings.invoice_lease_wait_seconds):
        t0 = time.perf_counter()
        result = read_isolated(data, _limits(settings))
        t1 = time.perf_counter()
    return result, {
        "wait_ms": round((t0 - t_wait) * 1000),
        "read_ms": round((t1 - t0) * 1000),
    }


def _run_out(
    result: ReadResult,
    timings: dict[str, int],
    *,
    doc: EvalDocument | None,
    filename: str | None,
) -> InvoiceRunOut:
    t = time.perf_counter()
    ex = extract_invoice(result.pages)
    timings["extract_ms"] = round((time.perf_counter() - t) * 1000)
    report: dict[str, Any] | None = field_report(ex, doc.invoice) if doc else None
    return InvoiceRunOut(
        source="sample" if doc else "upload",
        document=_document_out(doc) if doc else None,
        filename=filename,
        page_count=result.page_count,
        pages=[
            InvoicePageOut(
                number=p.number,
                width=p.width,
                height=p.height,
                method=p.method,
                preview=f"data:image/jpeg;base64,{p.preview}" if p.preview else None,
            )
            for p in result.pages
        ],
        extraction=InvoiceExtractionOut.model_validate(ex.to_json()),
        comparison=InvoiceComparisonOut.model_validate(report) if report else None,
        timings=timings,
    )


def run_sample(db: Database, settings: DocsSettings, doc_id: str) -> InvoiceRunOut:
    doc = find(settings, doc_id)
    t = time.perf_counter()
    pdf = _pdf(doc)
    render_ms = round((time.perf_counter() - t) * 1000)
    result, timings = _read(db, settings, pdf, f"invoice:{doc.id}")
    out = _run_out(result, {"render_ms": render_ms, **timings}, doc=doc, filename=None)
    log.info("docs.invoice_run", document=doc.id, exact=out.comparison and out.comparison.exact)
    return out


def run_upload(db: Database, settings: DocsSettings, data: bytes, filename: str) -> InvoiceRunOut:
    if not data:
        raise InvoiceError(422, "empty_file", "The file is empty.")
    if len(data) > settings.upload_max_bytes:
        mb = settings.upload_max_bytes // (1024 * 1024)
        raise InvoiceError(413, "too_large", f"PDFs up to {mb} MB can be uploaded.")
    if b"%PDF-" not in data[:1024]:
        raise InvoiceError(422, "not_a_pdf", "Only PDF files can be uploaded.")
    result, timings = _read(db, settings, data, "invoice:upload")
    out = _run_out(result, timings, doc=None, filename=filename)
    log.info(
        "docs.invoice_upload",
        pages=result.page_count,
        lines=len(out.extraction.lines),
        needs_review=out.extraction.needs_review,
    )
    return out
