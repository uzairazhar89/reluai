"""Rebuilding headings, paragraphs and the page map from positioned lines."""

from __future__ import annotations

from reluai_docs.layout import build_document, clean_text
from reluai_docs.pdfread import RawLine, RawPage
from reluai_retrieval.chunking import chunk_text


def line(text: str, top: float, *, size: float = 10, x0: float = 72, bold: bool = False,
         x1: float | None = None) -> RawLine:  # fmt: skip
    return RawLine(text, x0, top - 0.8 * size, x1 or x0 + 6 * len(text), top + 0.2 * size, size,
                   bold)  # fmt: skip


def page(n: int, lines: list[RawLine]) -> RawPage:
    return RawPage(n, 595, 842, "text", lines)


def body(top: float, texts: list[str]) -> list[RawLine]:
    return [line(t, top + 12 * i, x1=520) for i, t in enumerate(texts)]


def test_headings_paragraphs_and_running_lines() -> None:
    pages = []
    for n in range(1, 5):
        lines = [line("Example Ltd internal handbook", 40, size=8)]
        if n == 1:
            lines.append(line("Returns Handbook", 80, size=20))
        lines.append(line(f"{n} Section {n}", 120, size=14))
        lines += body(140, ["First line of the paragraph that wraps onto the", "next line."])
        # Different on each page: a bold line repeated on every page is a table header.
        lines.append(line(["Totals", "Summary", "Notes", "Remarks"][n - 1], 190, bold=True))
        lines += body(205, ["The second paragraph runs over", "three lines of ordinary text",
                            f"and ends here on page {n}."])  # fmt: skip
        lines.append(line(f"Page {n} of 4", 800, size=8))
        pages.append(page(n, lines))
    doc = build_document(pages)
    assert "internal handbook" not in doc.text and "Page 1 of 4" not in doc.text
    assert doc.text.startswith("# Returns Handbook\n\n## 1 Section 1\n\nFirst line")
    assert "wraps onto the next line." in doc.text
    assert "### Totals" in doc.text
    assert [o.title for o in doc.outline][:4] == ["Returns Handbook", "1 Section 1", "Totals",
                                                  "2 Section 2"]  # fmt: skip
    assert [o.level for o in doc.outline][:3] == [1, 2, 3]
    # Every passage maps back to the page it came from.
    for c in chunk_text(doc.text, max_words=20, overlap=0):
        p_from, p_to = doc.pages_for(c.start, c.end)
        numbered = [h for h in c.heading.split(" › ") if h[:1].isdigit()]
        n = int(numbered[-1].split()[0])
        assert p_from == p_to == n, (c.heading, c.text)


def test_paragraph_continues_across_pages_and_hyphenation() -> None:
    p1 = page(
        1,
        [
            line("Heading", 80, size=16),
            *body(110, ["The refund is paid to the origi-", "nal card and the customer is"]),
        ],
    )
    p2 = page(2, body(80, ["informed by email within two days.", "Short."]))
    doc = build_document([p1, p2])
    assert "paid to the original card and the customer is informed by email" in doc.text
    start = doc.text.index("informed")
    assert doc.page_starts[1] == start
    assert doc.page_of(start - 2) == 1
    assert doc.page_of(start) == 2


def test_bullets_and_indent_start_paragraphs() -> None:
    lines = [
        line("Keep the receipt.", 100, x1=200),
        line("• Report damage within fourteen days.", 112, x1=400),
        line("• Keep the packaging.", 124, x1=300),
    ]
    doc = build_document([page(1, lines)])
    assert doc.text.split("\n\n") == [
        "Keep the receipt.",
        "• Report damage within fourteen days.",
        "• Keep the packaging.",
    ]


def test_slides_do_not_become_all_headings() -> None:
    # Every line in a big font: nothing can be told apart, so no headings are invented.
    lines = [line(f"Point number {i} on this slide", 100 + 40 * i, size=24) for i in range(8)]
    doc = build_document([page(1, lines)])
    assert "#" not in doc.text
    assert doc.outline == []


def test_truncation_and_empty_pages() -> None:
    pages = [page(1, body(100, ["Word " * 30])), page(2, []), page(3, body(100, ["More " * 30]))]
    doc = build_document(pages, max_chars=200)
    assert doc.truncated
    assert len(doc.text) <= 200
    assert doc.page_starts == [0, len(doc.text), len(doc.text)]
    full = build_document(pages)
    assert full.page_starts[1] == full.page_starts[2]  # page 2 had nothing of its own
    assert full.page_of(full.page_starts[2]) == 3
    # A paragraph running on from the previous page is held to the same limit.
    running = [page(1, body(100, ["word " * 30])), page(2, body(100, ["more " * 30]))]
    cut = build_document(running, max_chars=200)
    assert cut.truncated and len(cut.text) <= 200


def test_clean_text() -> None:
    assert clean_text("eﬃcient ﬁnal  co­operate\x07") == "efficient final cooperate"
    # A paragraph that starts with "#" never becomes a Markdown heading.
    doc = build_document([page(1, body(100, ["# of items in the box is listed below."]))])
    assert not doc.text.startswith("#")


def test_numbered_headings_at_page_tops_are_not_running_headers() -> None:
    pages = [
        page(n, [line(f"Chapter {n}", 70, size=18), *body(100, [f"Text of chapter {n} here."]),
                 line(f"Page {n} of 4", 800, size=8)])
        for n in range(1, 5)
    ]  # fmt: skip
    doc = build_document(pages)
    assert [o.title for o in doc.outline] == ["Chapter 1", "Chapter 2", "Chapter 3", "Chapter 4"]
    assert "Page 2 of 4" not in doc.text


def test_weak_headings_need_to_stand_alone() -> None:
    lines = [
        line("Results are reported per carrier and per", 100, x1=520),
        line("MAP and MEASURE", 112, bold=True),  # small-caps words inside a sentence
        line("functions, and then summarised below.", 124, x1=400),
        line("Repeated header", 160, bold=True),
        line("Body text after it.", 172, x1=300),
    ]
    pages = [page(1, lines)] + [
        page(n, [line("Repeated header", 100, bold=True), *body(112, [f"Text on page {n}."])])
        for n in (2, 3)
    ]
    doc = build_document(pages)
    assert "MAP and MEASURE functions, and then" in doc.text
    assert doc.outline == []  # the repeated bold line is a table header, not a heading


def test_numbered_body_size_headings_nest() -> None:
    lines = [
        line("Report", 60, size=20),
        line("3. Risks", 100, bold=True),
        *body(112, ["Risks are introduced here with enough ordinary text to be a paragraph."]),
        line("3.2 Safety", 140, bold=True),
        *body(152, ["Safety is discussed in this paragraph, again in plain body text."]),
        line("Checklist", 180, bold=True),
        *body(192, ["Items to check are listed here as a sentence of normal length."]),
    ]
    doc = build_document([page(1, lines)])
    chunks = chunk_text(doc.text, max_words=40, overlap=0)
    assert [c.heading for c in chunks] == [
        "Report › 3. Risks",
        "Report › 3. Risks › 3.2 Safety",
        "Report › 3. Risks › 3.2 Safety › Checklist",
    ]


def test_heading_levels_follow_parent_numbers_without_gaps() -> None:
    returns = ["Returns are covered in this part of the handbook, in plain text that",
               "runs over two lines of ordinary length."]  # fmt: skip
    damaged = ["Damaged items are replaced at no cost to the customer, as set out in",
               "the paragraphs of this section."]  # fmt: skip
    contacts = ["Regional contacts are listed in this appendix for reference, with",
                "the hours each office is open."]  # fmt: skip
    lines = [
        line("Handbook", 40, size=22),
        line("1. Returns", 80, size=16),  # larger than the body: level 2 by size
        *body(100, returns),
        line("1.1 Damaged items", 140, bold=True),  # body size: one level under "1."
        *body(152, damaged),
        line("Appendix A", 200, size=22),
        line("Contacts by region", 230, bold=True),  # unnumbered: under the heading before it
        *body(242, contacts),
    ]
    doc = build_document([page(1, lines)])
    assert [(o.level, o.title) for o in doc.outline] == [
        (1, "Handbook"),
        (2, "1. Returns"),
        (3, "1.1 Damaged items"),
        (1, "Appendix A"),
        (2, "Contacts by region"),
    ]


def test_run_in_labels_join_their_text() -> None:
    lines = [
        line("Categories", 60, size=16),
        line("GOVERN 1:", 100, bold=True),
        *body(112, ["Policies and practices are in place and implemented effectively."]),
        line("GOVERN 2:", 140, bold=True),
        *body(152, ["Accountability structures are in place so the right teams act."]),
    ]
    doc = build_document([page(1, lines)])
    assert [o.title for o in doc.outline] == ["Categories"]
    assert "GOVERN 1: Policies and practices are in place" in doc.text
    assert "GOVERN 2: Accountability structures" in doc.text


def test_compound_hyphens_at_line_ends_are_kept() -> None:
    lines = body(
        100,
        [
            "Controls are context-specific and planned for the long term. Each control",
            "is reviewed in its context-",
            "specific setting by a manage-",
            "ment team as part of the long-",
            "term plan.",
        ],
    )
    text = build_document([page(1, lines)]).text
    # The document writes "context-specific" elsewhere, and uses "long" and "term" as words
    # but never "longterm"; "ment" is not a word, so "manage-ment" was a break.
    assert "its context-specific setting by a management team as part of the long-term plan" in text
