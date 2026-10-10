from __future__ import annotations

import pytest

from reluai_retrieval.chunking import chunk_text
from reluai_retrieval.citations import check_citations, cited_numbers, context_block
from reluai_retrieval.search import Hit, _strip_markers, reciprocal_rank_fusion

DOC = """Intro line before any heading.

# Refunds

Refunds go back to the original payment method. They take up to 5 working days.

## Damaged items

Report damage within 14 days of delivery. Send a photo if you can.
- Items under £10 do not need to be returned.
- Larger items are collected free of charge.

# Delivery

Orders ship within 2 working days."""


def test_chunks_are_exact_spans_with_heading_paths() -> None:
    chunks = chunk_text(DOC, max_words=40)
    for c in chunks:
        assert DOC[c.start : c.end] == c.text
        assert c.text == c.text.strip()
    headings = [c.heading for c in chunks]
    assert headings[0] == ""
    assert "Refunds" in headings
    assert "Refunds › Damaged items" in headings
    assert headings[-1] == "Delivery"
    assert [c.ordinal for c in chunks] == list(range(len(chunks)))


def test_small_budget_splits_sentences_and_overlaps() -> None:
    text = "# A\n\n" + " ".join(f"Sentence number {i} has five words." for i in range(12))
    chunks = chunk_text(text, max_words=12, overlap=1)
    assert len(chunks) > 3
    assert all(c.words <= 12 for c in chunks)
    # Consecutive chunks share one sentence.
    assert chunks[1].start < chunks[0].end


def test_overlong_sentences_become_word_windows() -> None:
    text = " ".join(f"w{i}" for i in range(55))
    chunks = chunk_text(text, max_words=20, overlap=0)
    assert [c.words for c in chunks] == [20, 20, 15]
    assert "".join(text[c.start : c.end] + " " for c in chunks).split() == text.split()


def test_every_word_is_covered() -> None:
    chunks = chunk_text(DOC, max_words=10, overlap=0)
    covered = " ".join(c.text for c in chunks)
    body = "\n".join(line for line in DOC.splitlines() if not line.startswith("#"))
    assert covered.split() == body.split()


@pytest.mark.parametrize("kwargs", [{"max_words": 5}, {"overlap": -1}])
def test_rejects_bad_settings(kwargs: dict[str, int]) -> None:
    with pytest.raises(ValueError, match=r"must|negative"):
        chunk_text(DOC, **kwargs)


def test_empty_text() -> None:
    assert chunk_text("") == []
    assert chunk_text("# Only a heading") == []


def test_citation_numbers() -> None:
    answer = "Refunds take 5 days [2]. Damage must be reported in 14 days [1, 3]. Again [2]."
    assert cited_numbers(answer) == [2, 1, 3]
    assert check_citations(answer, sources=2) == ([2, 1], [3])
    assert cited_numbers("No citations here, see section 2.") == []


def _hit(n: int, text: str) -> Hit:
    return Hit(
        chunk_id=n,
        document_id=1,
        external_id="policy",
        title="Policy",
        source="Synthetic",
        url=None,
        synthetic=True,
        heading=f"Section {n}",
        ordinal=n,
        char_start=0,
        char_end=len(text),
        text=text,
        score=1.0,
        snippet=text,
        highlights=[],
    )


def test_context_block_numbers_and_truncates() -> None:
    block = context_block([_hit(1, "short"), _hit(2, "word " * 400)], max_chars=50)
    assert block.startswith("[1] Policy › Section 1\nshort")
    assert "[2] Policy › Section 2" in block
    assert block.endswith(" …")


def test_highlight_markers_become_offsets() -> None:
    text, spans = _strip_markers("Report \x02damage\x03 within \x0214\x03 days")
    assert text == "Report damage within 14 days"
    assert [text[s:e] for s, e in spans] == ["damage", "14"]


def test_reciprocal_rank_fusion() -> None:
    fused = reciprocal_rank_fusion([[1, 2, 3], [3, 1, 4]])
    assert [i for i, _ in fused][:2] == [1, 3]
    assert {i for i, _ in fused} == {1, 2, 3, 4}
