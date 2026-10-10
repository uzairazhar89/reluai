"""Indexing and full-text search against a real PostgreSQL."""

from __future__ import annotations

import dataclasses

import pytest
from sqlalchemy import func, select, text

from reluai_core.db import Database
from reluai_retrieval.index import SourceDocument, index_document, remove_missing
from reluai_retrieval.models import Chunk, Document
from reluai_retrieval.search import search

pytestmark = pytest.mark.db

POLICY = SourceDocument(
    external_id="policy",
    title="Customer service policy",
    source="Written for this demo (synthetic)",
    synthetic=True,
    text="""# Refunds

Refunds are paid to the original payment method within 5 working days.

## Damaged items

Report damaged or faulty items within 14 days of delivery for a full refund.

# Delivery

UK orders are delivered in 2 to 4 working days. International orders take up to 10.

# Cancellations

Orders can be cancelled until they are dispatched.""",
)
OTHER = SourceDocument(
    external_id="faq",
    title="FAQ",
    source="Synthetic",
    synthetic=True,
    text="# Gift wrap\n\nGift wrap is available on most items.",
)


@pytest.fixture
def db(clean_db: Database) -> Database:
    with clean_db.session() as s:
        s.execute(text("TRUNCATE retrieval.document, retrieval.chunk RESTART IDENTITY CASCADE"))
    return clean_db


def test_indexing_is_idempotent(db: Database) -> None:
    with db.session() as s:
        first = index_document(s, "policy", POLICY, max_words=40)
        again = index_document(s, "policy", POLICY, max_words=40)
    assert first.changed
    assert not again.changed
    assert again.chunks == first.chunks
    with db.session() as s:
        assert s.scalar(select(func.count()).select_from(Document)) == 1
        assert s.scalar(select(func.count()).select_from(Chunk)) == first.chunks


def test_changed_text_replaces_chunks(db: Database) -> None:
    with db.session() as s:
        index_document(s, "policy", POLICY)
        edited = dataclasses.replace(POLICY, text=POLICY.text + "\n\nNew line.")
        result = index_document(s, "policy", edited)
    assert result.changed
    with db.session() as s:
        texts = s.scalars(select(Chunk.text)).all()
    assert any("New line." in t for t in texts)


def test_search_ranks_the_matching_section_first(db: Database) -> None:
    with db.session() as s:
        index_document(s, "policy", POLICY, max_words=40)
        index_document(s, "faq", OTHER)
        result = search(s, "policy", "how long do I have to report a damaged item?")
    assert result.match in {"all", "any"}
    top = result.hits[0]
    assert top.heading == "Refunds › Damaged items"
    assert "14 days" in top.text
    assert POLICY.text[top.char_start : top.char_end] == top.text
    assert any(top.snippet[a:b].lower().startswith("damag") for a, b in top.highlights)
    assert all(h.external_id == "policy" for h in result.hits)  # collections stay separate


def test_any_term_fallback_and_no_match(db: Database) -> None:
    with db.session() as s:
        index_document(s, "policy", POLICY, max_words=40)
        strict = search(s, "policy", "cancel dispatched order")
        loose = search(s, "policy", "cancel my order before shipping please, zebra")
        none = search(s, "policy", "zebra giraffe")
        empty = search(s, "policy", "   ")
    assert strict.match == "all"
    assert loose.match == "any"
    assert loose.hits[0].heading == "Cancellations"
    assert none.match == "none"
    assert none.hits == []
    assert empty.match == "none"


@pytest.mark.parametrize(
    "query",
    ["'; DROP TABLE retrieval.chunk; --", 'refund" OR 1=1', "!!! & | <-> :*", "\x00\x02"],
)
def test_hostile_queries_are_just_text(db: Database, query: str) -> None:
    with db.session() as s:
        index_document(s, "policy", POLICY)
        result = search(s, "policy", query.replace("\x00", ""))
        assert s.scalar(select(func.count()).select_from(Chunk)) > 0
    assert result.match in {"all", "any", "none"}


def test_remove_missing(db: Database) -> None:
    with db.session() as s:
        index_document(s, "policy", POLICY)
        index_document(s, "policy", OTHER)
        assert remove_missing(s, "policy", {"policy"}) == 1
    with db.session() as s:
        ids = s.scalars(select(Document.external_id)).all()
    assert ids == ["policy"]
