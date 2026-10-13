"""Meaning-based and hybrid search over a collection (pgvector + full-text).

Full-text search finds passages that share the question's words; vector search finds
passages that mean something similar even with different words ("how long do refunds
take" → "refunds are paid within five working days"). ``hybrid_search`` runs both and
merges the rankings with reciprocal-rank fusion, keeping each passage's rank in either list
so a consumer can show why it was retrieved.

Collections here are small (one document, a few hundred passages), so the vector search is
an exact scan over the collection's rows rather than an approximate index: exact results,
and no recall loss from filtering an approximate index by collection.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from reluai_retrieval.models import EMBEDDING_DIMENSIONS
from reluai_retrieval.search import (
    _ANY_TERM,
    _HEADLINE,
    MAX_QUERY_CHARS,
    Hit,
    Match,
    _strip_markers,
    reciprocal_rank_fusion,
    search,
)

# Constant SQL fragments only; every value is a bound parameter.
_VECTOR_SQL = f"""
SELECT c.id, c.document_id, d.external_id, d.title, d.source, d.url, d.synthetic,
       c.heading, c.ordinal, c.char_start, c.char_end, c.text,
       1 - (c.embedding <=> CAST(:v AS vector)) AS similarity,
       ts_headline('english', c.text, {_ANY_TERM}, :headline) AS snippet
FROM retrieval.chunk c
JOIN retrieval.document d ON d.id = c.document_id
WHERE d.collection = :collection AND c.embedding IS NOT NULL
ORDER BY c.embedding <=> CAST(:v AS vector), c.id
LIMIT :k
"""  # noqa: S608

_SIMILARITY_SQL = """
SELECT c.id, 1 - (c.embedding <=> CAST(:v AS vector)) AS similarity
FROM retrieval.chunk c
WHERE c.id IN :ids AND c.embedding IS NOT NULL
"""

SearchMode = Literal["hybrid", "keyword"]

# Passages that define something: the subject's words plus a defining verb. Constant SQL;
# the subject is bound and parsed by plainto_tsquery, so it can never become query syntax.
_DEFINITION_SQL = """
SELECT c.id
FROM retrieval.chunk c
JOIN retrieval.document d ON d.id = c.document_id
WHERE d.collection = :collection
  AND c.tsv @@ (plainto_tsquery('english', :q)
                && to_tsquery('english', 'defin:* | refer:* | mean:* | call:*'))
ORDER BY ts_rank_cd(c.tsv, plainto_tsquery('english', :q), 32) DESC, c.id
LIMIT :k
"""


def _literal(vector: np.ndarray | Sequence[float]) -> str:
    v = np.asarray(vector, dtype=np.float32).reshape(-1)
    if v.shape[0] != EMBEDDING_DIMENSIONS:
        raise ValueError(f"expected {EMBEDDING_DIMENSIONS} dimensions, got {v.shape[0]}")
    return "[" + ",".join(f"{x:.6g}" for x in v.tolist()) + "]"


def store_embeddings(session: Session, document_id: int, vectors: Mapping[int, np.ndarray]) -> int:
    """Set ``chunk.embedding`` for the given chunk ordinals of one document."""
    if not vectors:
        return 0
    session.execute(
        text(
            "UPDATE retrieval.chunk SET embedding = CAST(:v AS vector) "
            "WHERE document_id = :d AND ordinal = :o"
        ),
        [{"v": _literal(v), "d": document_id, "o": o} for o, v in vectors.items()],
    )
    return len(vectors)


@dataclass(frozen=True, slots=True)
class VectorHit:
    hit: Hit
    similarity: float


def vector_search(
    session: Session, collection: str, query_vector: np.ndarray, query: str, *, k: int = 20
) -> list[VectorHit]:
    rows = session.execute(
        text(_VECTOR_SQL),
        {
            "v": _literal(query_vector),
            "q": " ".join(query.split())[:MAX_QUERY_CHARS] or "-",
            "collection": collection,
            "k": max(1, min(k, 50)),
            "headline": _HEADLINE,
        },
    ).all()
    out: list[VectorHit] = []
    for r in rows:
        snippet, spans = _strip_markers(" ".join(str(r.snippet).split()))
        out.append(
            VectorHit(
                hit=Hit(
                    chunk_id=r.id,
                    document_id=r.document_id,
                    external_id=r.external_id,
                    title=r.title,
                    source=r.source,
                    url=r.url,
                    synthetic=r.synthetic,
                    heading=r.heading,
                    ordinal=r.ordinal,
                    char_start=r.char_start,
                    char_end=r.char_end,
                    text=r.text,
                    score=0.0,
                    snippet=snippet,
                    highlights=spans,
                ),
                similarity=round(float(r.similarity), 4),
            )
        )
    return out


_BY_ID_SQL = f"""
SELECT c.id, c.document_id, d.external_id, d.title, d.source, d.url, d.synthetic,
       c.heading, c.ordinal, c.char_start, c.char_end, c.text,
       ts_headline('english', c.text, {_ANY_TERM}, :headline) AS snippet
FROM retrieval.chunk c
JOIN retrieval.document d ON d.id = c.document_id
WHERE c.id IN :ids
"""  # noqa: S608


def _hits_by_id(session: Session, ids: list[int], query: str) -> dict[int, Hit]:
    rows = session.execute(
        text(_BY_ID_SQL).bindparams(bindparam("ids", expanding=True)),
        {"ids": ids, "q": " ".join(query.split())[:MAX_QUERY_CHARS] or "-", "headline": _HEADLINE},
    ).all()
    out: dict[int, Hit] = {}
    for r in rows:
        snippet, spans = _strip_markers(" ".join(str(r.snippet).split()))
        out[r.id] = Hit(
            chunk_id=r.id,
            document_id=r.document_id,
            external_id=r.external_id,
            title=r.title,
            source=r.source,
            url=r.url,
            synthetic=r.synthetic,
            heading=r.heading,
            ordinal=r.ordinal,
            char_start=r.char_start,
            char_end=r.char_end,
            text=r.text,
            score=0.0,
            snippet=snippet,
            highlights=spans,
        )
    return out


@dataclass(frozen=True, slots=True)
class FusedHit:
    hit: Hit
    fused: float
    keyword_rank: int | None
    vector_rank: int | None
    keyword_score: float | None
    similarity: float | None


@dataclass(frozen=True, slots=True)
class HybridResult:
    query: str
    mode: SearchMode
    keyword_match: Match
    hits: list[FusedHit] = field(default_factory=list)

    @property
    def best_similarity(self) -> float | None:
        sims = [h.similarity for h in self.hits if h.similarity is not None]
        return max(sims) if sims else None


def hybrid_search(
    session: Session,
    collection: str,
    query: str,
    query_vector: np.ndarray | None,
    *,
    k: int = 6,
    candidates: int = 20,
    define: str | None = None,
) -> HybridResult:
    """Top ``k`` passages by fused keyword and vector rank (keyword only without a vector).

    ``define``: for "what is X" questions, the subject X; passages that define it (its words
    with "defined", "refers to", "means" or "called") are added as a third ranking.
    """
    keyword = search(session, collection, query, k=candidates)
    definitions: list[int] = []
    if define and define.strip():
        definitions = list(
            session.scalars(
                text(_DEFINITION_SQL),
                {"q": define[:MAX_QUERY_CHARS], "collection": collection, "k": candidates},
            )
        )
    if query_vector is None and definitions:
        fused_kw = reciprocal_rank_fusion([[h.chunk_id for h in keyword.hits], definitions])
        hits = {h.chunk_id: h for h in keyword.hits}
        missing = [cid for cid, _ in fused_kw[:k] if cid not in hits]
        if missing:
            hits.update(_hits_by_id(session, missing, query))
        kw_rank_only = {h.chunk_id: i for i, h in enumerate(keyword.hits, start=1)}
        return HybridResult(
            query=keyword.query,
            mode="keyword",
            keyword_match=keyword.match,
            hits=[
                FusedHit(hits[cid], round(score, 6), kw_rank_only.get(cid), None,
                         hits[cid].score or None, None)
                for cid, score in fused_kw[:k]
                if cid in hits
            ],
        )  # fmt: skip
    if query_vector is None:
        return HybridResult(
            query=keyword.query,
            mode="keyword",
            keyword_match=keyword.match,
            hits=[
                FusedHit(h, 1.0 / (60 + i), i, None, h.score, None)
                for i, h in enumerate(keyword.hits[:k], start=1)
            ],
        )
    vector = vector_search(session, collection, query_vector, query, k=candidates)
    by_id: dict[int, Hit] = {h.chunk_id: h for h in keyword.hits}
    for v in vector:
        by_id.setdefault(v.hit.chunk_id, v.hit)
    kw_rank = {h.chunk_id: i for i, h in enumerate(keyword.hits, start=1)}
    kw_score = {h.chunk_id: h.score for h in keyword.hits}
    vec_rank = {v.hit.chunk_id: i for i, v in enumerate(vector, start=1)}
    sim = {v.hit.chunk_id: v.similarity for v in vector}
    # "Any term" keyword matches are weak evidence; they still count, at full RRF weight,
    # because rare-term questions often match only some words.
    fused = reciprocal_rank_fusion(
        [[h.chunk_id for h in keyword.hits], [v.hit.chunk_id for v in vector], definitions]
    )
    missing_hits = [cid for cid, _ in fused[:k] if cid not in by_id]
    if missing_hits:
        by_id.update(_hits_by_id(session, missing_hits, query))
    top = [cid for cid, _ in fused[:k]]
    missing = [cid for cid in top if cid not in sim]
    if missing:
        rows = session.execute(
            text(_SIMILARITY_SQL).bindparams(bindparam("ids", expanding=True)),
            {"v": _literal(query_vector), "ids": missing},
        ).all()
        sim.update({r.id: round(float(r.similarity), 4) for r in rows})
    score = dict(fused)
    return HybridResult(
        query=keyword.query,
        mode="hybrid",
        keyword_match=keyword.match,
        hits=[
            FusedHit(
                by_id[cid],
                round(score[cid], 6),
                kw_rank.get(cid),
                vec_rank.get(cid),
                kw_score.get(cid),
                sim.get(cid),
            )
            for cid in top
        ],
    )
