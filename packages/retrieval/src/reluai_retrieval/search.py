"""Full-text search over a collection, returning ranked, citable passages.

The query is parsed with ``websearch_to_tsquery`` (quotes for phrases, ``-`` to exclude,
``or``), so visitor text never becomes query syntax errors or SQL. If requiring every term
finds nothing, the search is repeated with any term matching, and the result says so: a
consumer can treat "any" matches as weaker evidence or abstain.

Snippets come from ``ts_headline`` with control-character markers, returned as plain text
plus ``(start, end)`` highlight offsets, so the website renders highlights without ever
inserting HTML from the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

MAX_QUERY_CHARS = 300
_START, _STOP = "\x02", "\x03"
_HEADLINE = (
    f"StartSel={_START}, StopSel={_STOP}, MaxWords=45, MinWords=18, "
    'MaxFragments=2, FragmentDelimiter=" … "'
)

_SQL = """
WITH q AS (SELECT {tsquery} AS query)
SELECT c.id, c.document_id, d.external_id, d.title, d.source, d.url, d.synthetic,
       c.heading, c.ordinal, c.char_start, c.char_end, c.text,
       ts_rank_cd(c.tsv, q.query, 32) AS score,
       ts_headline('english', c.text, q.query, :headline) AS snippet
FROM retrieval.chunk c
JOIN retrieval.document d ON d.id = c.document_id
CROSS JOIN q
WHERE d.collection = :collection AND c.tsv @@ q.query
ORDER BY score DESC, c.id
LIMIT :k
"""
_ALL_TERMS = "websearch_to_tsquery('english', :q)"
# plainto_tsquery joins lexemes with AND; its text form quotes every lexeme, so swapping the
# operator and casting back is safe for any input.
_ANY_TERM = "replace(plainto_tsquery('english', :q)::text, ' & ', ' | ')::tsquery"

Match = Literal["all", "any", "none"]


@dataclass(frozen=True, slots=True)
class Hit:
    chunk_id: int
    document_id: int
    external_id: str
    title: str
    source: str
    url: str | None
    synthetic: bool
    heading: str
    ordinal: int
    char_start: int
    char_end: int
    text: str
    score: float
    snippet: str
    highlights: list[tuple[int, int]]

    @property
    def label(self) -> str:
        return f"{self.title} › {self.heading}" if self.heading else self.title


@dataclass(frozen=True, slots=True)
class SearchResult:
    query: str
    match: Match
    hits: list[Hit] = field(default_factory=list)


def _strip_markers(marked: str) -> tuple[str, list[tuple[int, int]]]:
    out: list[str] = []
    spans: list[tuple[int, int]] = []
    pos = 0
    start: int | None = None
    for ch in marked:
        if ch == _START:
            start = pos
        elif ch == _STOP:
            if start is not None and pos > start:
                spans.append((start, pos))
            start = None
        else:
            out.append(ch)
            pos += 1
    return "".join(out), spans


def _run(session: Session, tsquery: str, collection: str, q: str, k: int) -> list[Hit]:
    rows = session.execute(
        text(_SQL.format(tsquery=tsquery)),
        {"q": q, "collection": collection, "k": k, "headline": _HEADLINE},
    ).all()
    hits: list[Hit] = []
    for r in rows:
        snippet, spans = _strip_markers(" ".join(str(r.snippet).split()))
        hits.append(
            Hit(
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
                score=round(float(r.score), 6),
                snippet=snippet,
                highlights=spans,
            )
        )
    return hits


def search(
    session: Session, collection: str, query: str, *, k: int = 5, min_score: float = 0.0
) -> SearchResult:
    """Top ``k`` passages for ``query``; all terms first, then any term."""
    q = " ".join(query.split())[:MAX_QUERY_CHARS]
    if not q:
        return SearchResult(query=q, match="none")
    k = max(1, min(k, 20))
    for match, tsquery in (("all", _ALL_TERMS), ("any", _ANY_TERM)):
        hits = [h for h in _run(session, tsquery, collection, q, k) if h.score >= min_score]
        if hits:
            return SearchResult(query=q, match=match, hits=hits)  # type: ignore[arg-type]
    return SearchResult(query=q, match="none")


def reciprocal_rank_fusion(rankings: list[list[int]], *, k: int = 60) -> list[tuple[int, float]]:
    """Merge several ranked id lists (e.g. full-text and vector search) into one.

    Score = Σ 1 / (k + rank), the standard RRF formula; ties keep first-seen order.
    """
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
