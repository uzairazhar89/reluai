"""Indexing: idempotent by content hash, so re-indexing unchanged documents is free."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from reluai_core.logging import get_logger
from reluai_retrieval.chunking import chunk_text
from reluai_retrieval.models import Chunk, Document

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SourceDocument:
    external_id: str
    title: str
    text: str
    source: str
    synthetic: bool
    url: str | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class IndexResult:
    document_id: int
    chunks: int
    changed: bool


def index_document(
    session: Session,
    collection: str,
    doc: SourceDocument,
    *,
    max_words: int = 160,
    overlap: int = 1,
) -> IndexResult:
    """Insert or replace one document and its chunks; unchanged content is left alone."""
    existing = session.scalars(
        select(Document).where(
            Document.collection == collection, Document.external_id == doc.external_id
        )
    ).first()
    if existing is not None and existing.content_sha256 == doc.sha256:
        count = session.scalars(select(Chunk.id).where(Chunk.document_id == existing.id)).all()
        return IndexResult(existing.id, len(count), changed=False)

    if existing is None:
        existing = Document(collection=collection, external_id=doc.external_id)
        session.add(existing)
    existing.title = doc.title
    existing.source = doc.source
    existing.url = doc.url
    existing.synthetic = doc.synthetic
    existing.content_sha256 = doc.sha256
    existing.text = doc.text
    existing.meta = doc.meta
    session.flush()
    session.execute(delete(Chunk).where(Chunk.document_id == existing.id))
    chunks = chunk_text(doc.text, max_words=max_words, overlap=overlap)
    session.add_all(
        Chunk(
            document_id=existing.id,
            ordinal=c.ordinal,
            heading=c.heading[:300],
            text=c.text,
            char_start=c.start,
            char_end=c.end,
            words=c.words,
        )
        for c in chunks
    )
    session.flush()
    log.info(
        "retrieval.indexed", collection=collection, document=doc.external_id, chunks=len(chunks)
    )
    return IndexResult(existing.id, len(chunks), changed=True)


def remove_missing(session: Session, collection: str, keep: set[str]) -> int:
    """Delete documents of a collection that are no longer in the source set."""
    stale = session.scalars(
        select(Document).where(Document.collection == collection, Document.external_id.not_in(keep))
    ).all()
    for d in stale:
        session.delete(d)
    return len(stale)
