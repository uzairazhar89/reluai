"""Background jobs: read uploaded PDFs, expire them, and re-run both evaluations daily."""

from __future__ import annotations

import uuid

from procrastinate import Blueprint

from reluai_core.cpu_lease import LeaseUnavailableError, cpu_lease
from reluai_core.jobs import QUEUE_DEFAULT
from reluai_core.logging import get_logger
from reluai_core.runtime import get_runtime
from reluai_docs import service
from reluai_docs.settings import get_docs_settings

blueprint = Blueprint()
log = get_logger(__name__)


@blueprint.task(name="process_document", queue=QUEUE_DEFAULT)
def process_document(document_id: str) -> None:
    rt = get_runtime()
    service.process_document(rt.db, get_docs_settings(), uuid.UUID(document_id))


@blueprint.periodic(cron="*/10 * * * *", periodic_id="docs-purge")
@blueprint.task(name="purge", queue=QUEUE_DEFAULT)
def purge(timestamp: int) -> None:
    rt = get_runtime()
    removed = service.purge(rt.db, get_docs_settings())
    log.info("docs.purged", removed=removed, timestamp=timestamp)


@blueprint.periodic(cron="17 4 * * *", periodic_id="docs-evaluation")
@blueprint.task(name="evaluation", queue=QUEUE_DEFAULT)
def evaluation(timestamp: int) -> None:
    """Re-run the extractive baseline on the sample so published results come from here."""
    from reluai_docs.evaluation import record_run, run_evaluation

    rt = get_runtime()
    settings = get_docs_settings()
    try:
        with cpu_lease(
            rt.db.engine, holder="docs-evaluation", wait_seconds=rt.settings.cpu_lease_wait_seconds
        ):
            summary = run_evaluation(rt.db, settings, label="extractive", mode="extractive")
    except LeaseUnavailableError:
        log.warning("docs.evaluation_skipped", reason="cpu lease busy")
        return
    if summary is None:
        log.warning("docs.evaluation_skipped", reason="sample not built")
        return
    record_run(rt.db, summary)
    log.info("docs.evaluation_done", correct=summary.correct, questions=summary.questions)


@blueprint.periodic(cron="47 4 * * *", periodic_id="docs-invoice-evaluation")
@blueprint.task(name="invoice_evaluation", queue=QUEUE_DEFAULT)
def invoice_evaluation(timestamp: int) -> None:
    """Re-run invoice extraction over the whole set (about two minutes of CPU, mostly OCR),
    so the published accuracy comes from this server."""
    from reluai_docs.invoices import service as invoices

    rt = get_runtime()
    settings = get_docs_settings()
    if not invoices.documents(settings):
        log.warning("docs.invoice_evaluation_skipped", reason="invoice set not built")
        return
    try:
        with cpu_lease(
            rt.db.engine,
            holder="docs-invoice-evaluation",
            wait_seconds=rt.settings.cpu_lease_wait_seconds,
        ):
            results = invoices.evaluate(settings)
    except LeaseUnavailableError:
        log.warning("docs.invoice_evaluation_skipped", reason="cpu lease busy")
        return
    run = invoices.record_run(rt.db, results)
    log.info("docs.invoice_evaluation_done", exact=run.exact, documents=run.documents)
