"""Numbered citations: the context a model sees and checks on the answer it writes.

Sources are numbered [1]..[n] in the order retrieved. ``context_block`` gives a model the
passages with their numbers; ``cited_numbers`` reads the numbers back out of an answer, and
``check_citations`` separates real citations from invented ones, which is how citation
precision is measured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from reluai_retrieval.search import Hit

_CITE = re.compile(r"\[(\d{1,2})(?:\s*,\s*(\d{1,2}))*\]")
_NUM = re.compile(r"\d{1,2}")


@dataclass(frozen=True, slots=True)
class Citation:
    number: int
    chunk_id: int
    document: str
    heading: str
    source: str
    url: str | None
    synthetic: bool
    quote: str
    highlights: list[tuple[int, int]]

    @classmethod
    def from_hit(cls, number: int, hit: Hit) -> Citation:
        return cls(
            number=number,
            chunk_id=hit.chunk_id,
            document=hit.title,
            heading=hit.heading,
            source=hit.source,
            url=hit.url,
            synthetic=hit.synthetic,
            quote=hit.snippet,
            highlights=hit.highlights,
        )


def number_hits(hits: list[Hit]) -> list[Citation]:
    return [Citation.from_hit(i, h) for i, h in enumerate(hits, start=1)]


def context_block(hits: list[Hit], *, max_chars: int = 1200) -> str:
    """Numbered passages for a prompt; each is cut to ``max_chars``."""
    parts = []
    for i, h in enumerate(hits, start=1):
        body = h.text if len(h.text) <= max_chars else h.text[:max_chars].rsplit(" ", 1)[0] + " …"
        parts.append(f"[{i}] {h.label}\n{body}")
    return "\n\n".join(parts)


def cited_numbers(answer: str) -> list[int]:
    """Citation numbers in order of first appearance: "see [2] and [1, 3]" → [2, 1, 3]."""
    seen: list[int] = []
    for m in _CITE.finditer(answer):
        for n in _NUM.findall(m.group(0)):
            value = int(n)
            if value not in seen:
                seen.append(value)
    return seen


def check_citations(answer: str, sources: int) -> tuple[list[int], list[int]]:
    """(valid, invented) citation numbers for an answer given ``sources`` passages."""
    numbers = cited_numbers(answer)
    return [n for n in numbers if 1 <= n <= sources], [n for n in numbers if not 1 <= n <= sources]
