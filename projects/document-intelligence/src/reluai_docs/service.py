"""Documents for the website: upload, process (in the worker), ask, inspect, delete, expire.

Flow of an upload:

1. The API checks size and file signature, writes the bytes to the spool (an in-memory
   volume shared with the worker, never disk) and records the document as ``queued``.
2. A job in the worker takes the global CPU lease, reads the spooled file and deletes it at
   once, then runs the isolated reader (text layer, OCR for scans), rebuilds headings and
   paragraphs, indexes the passages for full-text search and embeds them for vector search.
   The record's status and progress are updated as it goes, so the page can show them.
3. Questions are answered from that document only; after ``upload_ttl_minutes`` the record,
   its text and its passages are deleted.
"""

from __future__ import annotations

import os
import re
import time
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from reluai_core.cpu_lease import LeaseUnavailableError, cpu_lease
from reluai_core.db import Database
from reluai_core.logging import get_logger
from reluai_docs.answer import (
    NOT_FOUND,
    Answer,
    Passage,
    definition_subject,
    extractive_answer,
    model_answer,
)
from reluai_docs.embedding import TextEmbedder, load_embedder
from reluai_docs.isolation import ReaderLimits, read_isolated
from reluai_docs.layout import BuiltDocument, build_document
from reluai_docs.models import DocumentRecord, collection_for
from reluai_docs.pdfread import ReadError, ReadLimits, ReadResult
from reluai_docs.sample import SAMPLE, load_sample
from reluai_docs.schemas import (
    AnswerOut,
    AttemptOut,
    ChunkOut,
    ChunksOut,
    DocumentOut,
    DocumentSourceOut,
    OutlineOut,
    PassageOut,
    QuestionRequest,
    QuoteOut,
)
from reluai_docs.settings import DocsSettings
from reluai_inference.chain import ProviderChain
from reluai_retrieval.index import SourceDocument, index_document
from reluai_retrieval.models import Chunk, Document
from reluai_retrieval.vector import hybrid_search, store_embeddings

log = get_logger(__name__)

SAMPLE_ID = uuid.uuid5(uuid.NAMESPACE_URL, "https://reluai.cloud/docs/sample/" + SAMPLE.id)
EmbedderLoader = Callable[[], TextEmbedder | None]
ChainFactory = Callable[[bool], ProviderChain | None]  # argument: hosted models allowed
_FILENAME = re.compile(r"[^\w .()\-]+")
_JUNK_TITLE = re.compile(r"microsoft|untitled|\.docx?$|\.pdf$|^document\d*$", re.IGNORECASE)


class DocumentError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def default_embedder(settings: DocsSettings) -> EmbedderLoader:
    return lambda: load_embedder(settings.model_dir, threads=settings.embed_threads)


def safe_filename(name: str | None) -> str:
    base = os.path.basename((name or "").replace("\\", "/"))
    base = " ".join(_FILENAME.sub("", base).split())[:120]
    return base or "document.pdf"


# --------------------------------------------------------------------------- output
def _warnings(rec: DocumentRecord) -> list[str]:
    out: list[str] = []
    if rec.page_count > rec.pages_read and rec.pages_read:
        out.append(f"Only the first {rec.pages_read} of {rec.page_count} pages were read.")
    if rec.ocr_skipped:
        pages = ", ".join(str(p) for p in rec.ocr_skipped[:10])
        more = " …" if len(rec.ocr_skipped) > 10 else ""
        out.append(
            f"{len(rec.ocr_skipped)} scanned page(s) were not read because OCR is limited "
            f"per document: page {pages}{more}."
        )
    if rec.truncated:
        out.append("The text was longer than the demo indexes; the end was left out.")
    if rec.status == "ready" and rec.search_mode == "keyword":
        out.append("The embedding model is not installed here, so search is by keywords only.")
    return out


def document_out(rec: DocumentRecord, *, llm: bool, external_llm: bool) -> DocumentOut:
    source = None
    if rec.kind == "sample":
        source = DocumentSourceOut(
            title=SAMPLE.title,
            publisher=SAMPLE.publisher,
            url=SAMPLE.url,
            licence=SAMPLE.licence,
            sha256=SAMPLE.sha256,
        )
    return DocumentOut(
        id=rec.id,
        kind=rec.kind,  # type: ignore[arg-type]
        filename=rec.filename,
        title=rec.title,
        status=rec.status,  # type: ignore[arg-type]
        progress_done=rec.progress_done,
        progress_total=rec.progress_total,
        file_bytes=rec.file_bytes,
        page_count=rec.page_count,
        pages_read=rec.pages_read,
        pages_text=rec.pages_text,
        pages_ocr=rec.pages_ocr,
        pages_empty=rec.pages_empty,
        ocr_skipped=list(rec.ocr_skipped or []),
        chars=rec.chars,
        chunks=rec.chunks,
        truncated=rec.truncated,
        search_mode=rec.search_mode,  # type: ignore[arg-type]
        embedding_model=rec.embedding_model,
        outline=[OutlineOut(**o) for o in (rec.outline or [])],
        warnings=_warnings(rec),
        error_code=rec.error_code,
        error_message=rec.error_message,
        created_at=rec.created_at,
        expires_at=rec.expires_at,
        timings=dict(rec.timings or {}),
        source=source,
        llm_available=llm,
        external_llm_available=external_llm,
    )


# --------------------------------------------------------------------------- upload
PROCESSING = ("queued", "reading", "ocr", "indexing", "embedding")


def pending(db: Database) -> int:
    with db.session() as s:
        return int(
            s.scalar(
                select(func.count())
                .select_from(DocumentRecord)
                .where(DocumentRecord.status.in_(PROCESSING))
            )
            or 0
        )


def create_upload(
    db: Database, settings: DocsSettings, *, visitor: str, data: bytes, filename: str | None
) -> DocumentRecord:
    if not data:
        raise DocumentError(422, "empty_file", "The file is empty.")
    if len(data) > settings.upload_max_bytes:
        mb = settings.upload_max_bytes // (1024 * 1024)
        raise DocumentError(413, "too_large", f"PDFs up to {mb} MB can be uploaded.")
    if b"%PDF-" not in data[:1024]:
        raise DocumentError(422, "not_a_pdf", "Only PDF files can be uploaded.")
    doc_id = uuid.uuid4()
    settings.spool_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = settings.spool_dir / f"{doc_id.hex}.pdf"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    now = datetime.now(UTC)
    rec = DocumentRecord(
        id=doc_id,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(minutes=settings.upload_ttl_minutes),
        kind="upload",
        visitor_key=visitor,
        filename=safe_filename(filename),
        file_bytes=len(data),
        status="queued",
        progress_done=0,
        progress_total=0,
        page_count=0,
        pages_read=0,
        pages_text=0,
        pages_ocr=0,
        pages_empty=0,
        ocr_skipped=[],
        chars=0,
        chunks=0,
        truncated=False,
        outline=[],
        page_starts=[],
        timings={},
    )
    try:
        with db.session() as s:
            s.add(rec)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    log.info("docs.upload_queued", document=doc_id.hex[:8], bytes=len(data))
    return rec


def _update(db: Database, doc_id: uuid.UUID, **values: Any) -> None:
    with db.session() as s:
        s.execute(
            DocumentRecord.__table__.update()  # type: ignore[attr-defined]
            .where(DocumentRecord.id == doc_id)
            .values(updated_at=datetime.now(UTC), **values)
        )


def _fail(db: Database, doc_id: uuid.UUID, code: str, message: str) -> None:
    log.info("docs.upload_failed", document=doc_id.hex[:8], code=code)
    _update(db, doc_id, status="failed", error_code=code[:30], error_message=message[:300])


def _title(result: ReadResult, built: BuiltDocument, filename: str) -> str:
    first = next((o.title for o in built.outline if o.page <= 2 and o.level == 1), None)
    if first:
        return first[:200]
    if result.title and not _JUNK_TITLE.search(result.title):
        return result.title[:200]
    return filename.removesuffix(".pdf").removesuffix(".PDF")[:200] or filename


def _embed_texts(db: Session, retrieval_doc_id: int) -> list[tuple[int, str]]:
    rows = db.execute(
        select(Chunk.ordinal, Chunk.heading, Chunk.text)
        .where(Chunk.document_id == retrieval_doc_id)
        .order_by(Chunk.ordinal)
    ).all()
    return [(r.ordinal, f"{r.heading}\n{r.text}" if r.heading else r.text) for r in rows]


def process_document(
    db: Database,
    settings: DocsSettings,
    doc_id: uuid.UUID,
    *,
    embedder: EmbedderLoader | None = None,
    use_lease: bool = True,
) -> None:
    """The worker job: read the spooled PDF, index and embed it. Idempotent."""
    embedder = embedder or default_embedder(settings)
    with db.session() as s:
        rec = s.get(DocumentRecord, doc_id)
        if rec is None or rec.status != "queued":
            return
        filename = rec.filename
    path = settings.spool_dir / f"{doc_id.hex}.pdf"
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        _fail(
            db,
            doc_id,
            "upload_lost",
            "The upload was lost before it could be read (the server restarted); upload it again.",
        )
        return
    finally:
        path.unlink(missing_ok=True)

    t_wait = time.perf_counter()
    lease: AbstractContextManager[None] = (
        cpu_lease(db.engine, holder=f"docs-read:{doc_id.hex[:8]}",
                  wait_seconds=settings.lease_wait_seconds)
        if use_lease else nullcontext()
    )  # fmt: skip
    last = [0.0]

    def progress(stage: str, done: int, total: int) -> None:
        now = time.perf_counter()
        if now - last[0] < 0.3 and done not in (0, total):
            return
        last[0] = now
        _update(db, doc_id, status=stage, progress_done=done, progress_total=total)

    try:
        with lease:
            timings = {"wait_ms": round((time.perf_counter() - t_wait) * 1000)}
            _update(db, doc_id, status="reading")
            t0 = time.perf_counter()
            result = read_isolated(
                data,
                ReaderLimits(
                    ReadLimits(
                        max_pages=settings.max_pages,
                        max_ocr_pages=settings.max_ocr_pages,
                        ocr_dpi=settings.ocr_dpi,
                        ocr_max_pixels=settings.ocr_max_pixels,
                        ocr_threads=settings.embed_threads,
                    ),
                    timeout_seconds=settings.read_timeout_seconds,
                    cpu_seconds=settings.read_cpu_seconds,
                    memory_mb=settings.read_memory_mb,
                    max_bytes=settings.upload_max_bytes,
                ),
                progress,
            )
            del data
            timings["read_ms"] = round((time.perf_counter() - t0) * 1000)
            _index(
                db,
                settings,
                doc_id,
                result,
                filename=filename,
                timings=timings,
                embedder_loader=embedder,
            )
    except ReadError as exc:
        _fail(db, doc_id, exc.code, exc.message)
    except LeaseUnavailableError:
        _fail(db, doc_id, "busy", "The server is busy with other work; try again in a minute.")
    except Exception:
        log.exception("docs.process_failed", document=doc_id.hex[:8])
        _fail(db, doc_id, "failed", "Something went wrong while reading this PDF.")


def _index(
    db: Database,
    settings: DocsSettings,
    doc_id: uuid.UUID,
    result: ReadResult,
    *,
    filename: str,
    timings: dict[str, int],
    embedder_loader: EmbedderLoader,
) -> None:
    t0 = time.perf_counter()
    built = build_document(result.pages, max_chars=settings.max_chars)
    counts = {
        "page_count": result.page_count,
        "pages_read": len(result.pages),
        "pages_text": sum(1 for p in result.pages if p.method == "text"),
        "pages_ocr": sum(1 for p in result.pages if p.method == "ocr"),
        "pages_empty": sum(1 for p in result.pages if p.method == "empty"),
        "ocr_skipped": result.ocr_skipped,
    }
    if not built.text.strip():
        _update(db, doc_id, **counts)
        message = (
            "No text was found: the scanned pages are beyond this demo's OCR limit."
            if result.ocr_skipped
            else "No text was found in this PDF (it may contain only images or drawings)."
        )
        _fail(db, doc_id, "no_text", message)
        return
    title = _title(result, built, filename)
    _update(db, doc_id, status="indexing", progress_done=0, progress_total=0, **counts)
    with db.session() as s:
        indexed = index_document(
            s,
            collection_for(doc_id),
            SourceDocument(
                external_id=doc_id.hex,
                title=title,
                text=built.text,
                source="Uploaded PDF",
                synthetic=False,
            ),
            max_words=settings.chunk_words,
            overlap=settings.chunk_overlap,
        )
        texts = _embed_texts(s, indexed.document_id)
    timings["index_ms"] = round((time.perf_counter() - t0) * 1000)

    mode, model_name = "keyword", None
    embedder = embedder_loader()
    if embedder is not None and texts:
        t1 = time.perf_counter()
        vectors: dict[int, np.ndarray] = {}
        batch = 32
        for start in range(0, len(texts), batch):
            _update(db, doc_id, status="embedding", progress_done=start, progress_total=len(texts))
            part = texts[start : start + batch]
            emb = embedder.embed([t for _, t in part])
            vectors.update({o: emb[i] for i, (o, _) in enumerate(part)})
        with db.session() as s:
            store_embeddings(s, indexed.document_id, vectors)
        mode, model_name = "hybrid", embedder.name
        timings["embed_ms"] = round((time.perf_counter() - t1) * 1000)

    _update(
        db,
        doc_id,
        status="ready",
        progress_done=0,
        progress_total=0,
        title=title,
        chars=len(built.text),
        chunks=indexed.chunks,
        truncated=built.truncated,
        search_mode=mode,
        embedding_model=model_name,
        outline=[{"level": o.level, "title": o.title, "page": o.page} for o in built.outline][:300],
        page_starts=built.page_starts,
        retrieval_document_id=indexed.document_id,
        timings=timings,
    )
    log.info(
        "docs.upload_ready",
        document=doc_id.hex[:8],
        pages=len(result.pages),
        chunks=indexed.chunks,
        mode=mode,
        **timings,
    )


# --------------------------------------------------------------------------- sample
def ensure_sample(db: Database, settings: DocsSettings) -> DocumentRecord | None:
    """Load the bundled sample into the database once; None if it was not built."""
    payload = load_sample(settings.sample_path)
    if payload is None:
        return None
    marker = int(payload["text_sha256"][:12], 16)

    def current(s: Session) -> DocumentRecord | None:
        rec = s.get(DocumentRecord, SAMPLE_ID)
        if rec is not None and rec.status == "ready" and rec.timings.get("text_sha") == marker:
            s.expunge(rec)
            return rec
        return None

    with db.session() as s:
        found = current(s)
    if found is not None:
        return found
    with db.session() as s:
        # One loader at a time across API processes; the others wait and then see it done.
        s.execute(text("SELECT pg_advisory_xact_lock(hashtext('reluai-docs-sample'))"))
        found = current(s)
        if found is not None:
            return found
        rec = s.get(DocumentRecord, SAMPLE_ID)
        indexed = index_document(
            s,
            collection_for(SAMPLE_ID),
            SourceDocument(
                external_id=SAMPLE.id,
                title=SAMPLE.title,
                text=payload["text"],
                source=SAMPLE.publisher,
                synthetic=False,
                url=SAMPLE.url,
            ),
            max_words=int(payload["chunk_words"]),
            overlap=int(payload["chunk_overlap"]),
        )
        mode, model = "keyword", None
        vectors = payload.get("embeddings")
        if vectors and len(vectors) == indexed.chunks:
            store_embeddings(
                s,
                indexed.document_id,
                {i: np.asarray(v, dtype=np.float32) for i, v in enumerate(vectors)},
            )
            mode, model = "hybrid", payload.get("embedding_model")
        values: dict[str, Any] = {
            "kind": "sample",
            "visitor_key": None,
            "expires_at": None,
            "filename": SAMPLE.filename,
            "file_bytes": int(payload["file_bytes"]),
            "status": "ready",
            "progress_done": 0,
            "progress_total": 0,
            "page_count": int(payload["page_count"]),
            "pages_read": int(payload["page_count"]),
            "pages_text": int(payload["pages_text"]),
            "pages_ocr": 0,
            "pages_empty": int(payload["pages_empty"]),
            "ocr_skipped": [],
            "chars": len(payload["text"]),
            "chunks": indexed.chunks,
            "truncated": False,
            "search_mode": mode,
            "embedding_model": model,
            "title": SAMPLE.title,
            "outline": payload["outline"][:300],
            "page_starts": payload["page_starts"],
            "retrieval_document_id": indexed.document_id,
            "error_code": None,
            "error_message": None,
            "timings": {"text_sha": marker},
            "updated_at": datetime.now(UTC),
        }
        if rec is None:
            rec = DocumentRecord(id=SAMPLE_ID, **values)
            s.add(rec)
        else:
            for k, v in values.items():
                setattr(rec, k, v)
        s.flush()
        s.refresh(rec)
        s.expunge(rec)
    log.info("docs.sample_loaded", chunks=indexed.chunks, mode=mode)
    return rec


# --------------------------------------------------------------------------- read
def get_record(db: Database, doc_id: uuid.UUID, *, visitor: str | None) -> DocumentRecord:
    with db.session() as s:
        rec = s.get(DocumentRecord, doc_id)
        if rec is not None:
            s.expunge(rec)
    if rec is None or (rec.expires_at is not None and rec.expires_at <= datetime.now(UTC)):
        raise DocumentError(
            404,
            "document_not_found",
            "This document has expired or does not exist. Uploads are deleted after an hour.",
        )
    if rec.kind == "upload" and visitor is not None and rec.visitor_key != visitor:
        raise DocumentError(
            403, "not_your_document", "Only the visitor who uploaded this document can open it."
        )
    return rec


def _pages(starts: list[int], start: int, end: int) -> tuple[int, int]:
    built = BuiltDocument(text="", page_starts=starts)
    return built.pages_for(start, end) if starts else (1, 1)


def chunks(db: Database, rec: DocumentRecord, *, offset: int, limit: int) -> ChunksOut:
    if rec.retrieval_document_id is None:
        return ChunksOut(total=0, offset=offset, items=[])
    with db.session() as s:
        total = s.scalar(
            select(func.count())
            .select_from(Chunk)
            .where(Chunk.document_id == rec.retrieval_document_id)
        )
        rows = s.scalars(
            select(Chunk)
            .where(Chunk.document_id == rec.retrieval_document_id)
            .order_by(Chunk.ordinal)
            .offset(offset)
            .limit(limit)
        ).all()
        items = []
        for c in rows:
            p_from, p_to = _pages(rec.page_starts, c.char_start, c.char_end)
            items.append(
                ChunkOut(
                    ordinal=c.ordinal,
                    heading=c.heading,
                    page_from=p_from,
                    page_to=p_to,
                    words=c.words,
                    text=c.text,
                )
            )
    return ChunksOut(total=int(total or 0), offset=offset, items=items)


# --------------------------------------------------------------------------- ask
def ask(
    db: Database,
    settings: DocsSettings,
    rec: DocumentRecord,
    body: QuestionRequest,
    *,
    visitor: str | None,
    chain_factory: ChainFactory,
    embedder: EmbedderLoader | None = None,
) -> AnswerOut:
    if rec.status != "ready":
        raise DocumentError(409, "not_ready", "This document is still being processed.")
    question = " ".join(body.question.split())[: settings.question_max_chars]
    model = (embedder or default_embedder(settings))() if rec.search_mode == "hybrid" else None
    t0 = time.perf_counter()
    qv = model.embed_query(question) if model is not None else None
    with db.session() as s:
        found = hybrid_search(
            s,
            collection_for(rec.id),
            question,
            qv,
            k=settings.passages,
            candidates=settings.candidates,
            define=definition_subject(question),
        )
    retrieval_ms = round((time.perf_counter() - t0) * 1000)
    passages = []
    for i, h in enumerate(found.hits, start=1):
        p_from, p_to = _pages(rec.page_starts, h.hit.char_start, h.hit.char_end)
        passages.append(
            Passage(
                number=i,
                chunk_id=h.hit.chunk_id,
                heading=h.hit.heading,
                text=h.hit.text,
                page_from=p_from,
                page_to=p_to,
                snippet=h.hit.snippet,
                highlights=h.hit.highlights,
                keyword_rank=h.keyword_rank,
                vector_rank=h.vector_rank,
                similarity=h.similarity,
            )
        )

    t1 = time.perf_counter()
    answer: Answer | None = None
    fallback: str | None = None
    if not passages:
        answer = Answer(NOT_FOUND, [], True, "extractive", note="no passage matched the question")
    elif body.mode == "extractive":
        fallback = "extractive answer requested"
    else:
        external = rec.kind == "sample" or body.allow_external
        chain = chain_factory(external)
        if chain is None:
            needs_consent = not external and chain_factory(True) is not None
            fallback = (
                "sending the passages to the hosted model needs your consent"
                if needs_consent
                else "no model is configured on this server"
            )
        else:
            answer = model_answer(question, passages, chain, visitor=visitor)
            if not answer.usable:
                fallback = "the model did not return a usable answer"
    if answer is not None and not answer.usable:
        spent = answer
        answer = extractive_answer(question, passages, embedder=model, query_vector=qv)
        answer.attempts, answer.retries = spent.attempts, spent.retries
        answer.prompt_tokens, answer.completion_tokens = (
            spent.prompt_tokens,
            spent.completion_tokens,
        )
    elif answer is None:
        answer = extractive_answer(question, passages, embedder=model, query_vector=qv)
    answer_ms = round((time.perf_counter() - t1) * 1000)
    log.info(
        "docs.asked",
        kind=rec.kind,
        method=answer.method,
        abstained=answer.abstained,
        passages=len(passages),
        tokens=answer.tokens,
        retrieval_ms=retrieval_ms,
        answer_ms=answer_ms,
        word_overlap=answer.word_overlap,
        similarity=answer.similarity,
    )
    return AnswerOut(
        question=question,
        answer=answer.text,
        citations=answer.citations,
        abstained=answer.abstained,
        method=answer.method,
        note=answer.note,
        fallback_reason=fallback if answer.method == "extractive" else None,
        quotes=[QuoteOut(number=q.number, start=q.start, end=q.end) for q in answer.quotes],
        passages=[
            PassageOut(
                number=p.number,
                heading=p.heading,
                page_from=p.page_from,
                page_to=p.page_to,
                text=p.text,
                snippet=p.snippet,
                highlights=p.highlights,
                keyword_rank=p.keyword_rank,
                vector_rank=p.vector_rank,
                similarity=p.similarity,
            )
            for p in passages
        ],
        search_mode=found.mode,
        keyword_match=found.keyword_match,
        provider=answer.provider,
        model=answer.model,
        tokens=answer.tokens,
        retries=answer.retries,
        attempts=[
            AttemptOut(
                provider=a.provider, model=a.model, outcome=a.outcome, latency_ms=a.latency_ms
            )
            for a in answer.attempts
        ],
        retrieval_ms=retrieval_ms,
        answer_ms=answer_ms,
        word_overlap=answer.word_overlap,
        similarity=answer.similarity,
    )


# --------------------------------------------------------------------------- delete / expire
def _drop(s: Session, doc_id: uuid.UUID) -> None:
    s.execute(delete(Document).where(Document.collection == collection_for(doc_id)))
    s.execute(delete(DocumentRecord).where(DocumentRecord.id == doc_id))


def delete_document(db: Database, settings: DocsSettings, rec: DocumentRecord) -> None:
    if rec.kind != "upload":
        raise DocumentError(403, "not_deletable", "The bundled sample cannot be deleted.")
    with db.session() as s:
        _drop(s, rec.id)
    (settings.spool_dir / f"{rec.id.hex}.pdf").unlink(missing_ok=True)
    log.info("docs.deleted", document=rec.id.hex[:8])


def purge(db: Database, settings: DocsSettings, *, stuck_minutes: int = 15) -> int:
    """Delete expired uploads; fail uploads stuck in the queue; clear orphaned spool files."""
    now = datetime.now(UTC)
    with db.session() as s:
        expired = s.scalars(
            select(DocumentRecord.id).where(
                DocumentRecord.expires_at.is_not(None), DocumentRecord.expires_at <= now
            )
        ).all()
        for doc_id in expired:
            _drop(s, doc_id)
        stuck = s.scalars(
            select(DocumentRecord.id).where(
                DocumentRecord.status.in_(PROCESSING),
                DocumentRecord.updated_at < now - timedelta(minutes=stuck_minutes),
            )
        ).all()
    for doc_id in stuck:
        _fail(db, doc_id, "timeout", "Processing did not finish; upload the file again.")
    if settings.spool_dir.is_dir():
        cutoff = time.time() - stuck_minutes * 60
        for f in settings.spool_dir.glob("*.pdf"):
            try:
                if f.stat().st_mtime < cutoff:
                    f.unlink(missing_ok=True)
            except FileNotFoundError:
                continue
    return len(expired)
