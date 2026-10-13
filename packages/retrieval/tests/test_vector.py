"""Embeddings in pgvector, vector search and hybrid fusion, against a real PostgreSQL.

Vectors here are hand-made one-hot "topics" so the expected order is obvious; the real
model is exercised in the Document Intelligence project.
"""

from __future__ import annotations

import numpy as np
import pytest

from reluai_core.db import Database
from reluai_retrieval.index import SourceDocument, index_document
from reluai_retrieval.models import EMBEDDING_DIMENSIONS
from reluai_retrieval.vector import hybrid_search, store_embeddings, vector_search

pytestmark = pytest.mark.db

TEXT = """# Refunds

Refunds are paid to the original payment method within five working days.

# Delivery

Parcels arrive in two to four working days within the United Kingdom.

# Returns

Unwanted items may be sent back within thirty days of arrival."""


def topic(*weights: tuple[int, float]) -> np.ndarray:
    v = np.zeros(EMBEDDING_DIMENSIONS, dtype=np.float32)
    for i, w in weights:
        v[i] = w
    return v / np.linalg.norm(v)


@pytest.fixture
def doc(clean_db: Database) -> int:
    with clean_db.session() as s:
        res = index_document(
            s,
            "vec",
            SourceDocument("d", "Policy", TEXT, "test", synthetic=True),
            max_words=40,
            overlap=0,
        )
        assert res.chunks == 3
        # chunk 0 refunds, 1 delivery, 2 returns
        store_embeddings(
            s, res.document_id, {0: topic((0, 1)), 1: topic((1, 1)), 2: topic((2, 1), (0, 0.4))}
        )
        return res.document_id


def test_vector_search_orders_by_similarity(clean_db: Database, doc: int) -> None:
    with clean_db.session() as s:
        hits = vector_search(s, "vec", topic((2, 1)), "send back", k=3)
    assert [h.hit.heading for h in hits] == ["Returns", "Refunds", "Delivery"]
    assert hits[0].similarity == pytest.approx(0.928, abs=0.01)
    assert hits[2].similarity == pytest.approx(0.0, abs=1e-6)


def test_hybrid_finds_a_paraphrase_keywords_miss(clean_db: Database, doc: int) -> None:
    with clean_db.session() as s:
        # No word of the question is in the "Returns" passage; the vector finds it.
        res = hybrid_search(s, "vec", "send goods", topic((2, 1)), k=2)
    assert res.mode == "hybrid"
    assert res.keyword_match == "none"
    top = res.hits[0]
    assert top.hit.heading == "Returns"
    assert (top.keyword_rank, top.vector_rank) == (None, 1)
    assert top.similarity == pytest.approx(0.928, abs=0.01)


def test_hybrid_fuses_both_rankings(clean_db: Database, doc: int) -> None:
    with clean_db.session() as s:
        res = hybrid_search(s, "vec", "working days", topic((0, 1)), k=3)
    # "working days" matches Refunds and Delivery by keyword; the vector favours Refunds.
    assert [h.hit.heading for h in res.hits][:2] == ["Refunds", "Delivery"]
    assert res.hits[0].keyword_rank is not None and res.hits[0].vector_rank == 1
    assert all(h.similarity is not None for h in res.hits)


def test_keyword_only_without_a_query_vector(clean_db: Database, doc: int) -> None:
    with clean_db.session() as s:
        res = hybrid_search(s, "vec", "thirty days", None, k=2)
    assert res.mode == "keyword"
    assert res.hits[0].hit.heading == "Returns"
    assert res.hits[0].vector_rank is None


def test_wrong_dimensions_are_rejected(clean_db: Database, doc: int) -> None:
    with clean_db.session() as s, pytest.raises(ValueError, match="dimensions"):
        vector_search(s, "vec", np.ones(10), "x")
