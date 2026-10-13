"""The isolated PDF reader: text layer, OCR for scans, limits and unreadable files."""

from __future__ import annotations

import io

import pytest
from reportlab.pdfgen.canvas import Canvas

from reluai_docs.isolation import ReaderLimits, read_isolated
from reluai_docs.layout import build_document
from reluai_docs.pdfread import ReadError, ReadLimits

from .pdfs import SCAN_PAGE, policy_pdf, scanned_pdf


def limits(**read: int) -> ReaderLimits:
    return ReaderLimits(ReadLimits(**read), timeout_seconds=60)


def test_text_pdf_with_headings_and_pages() -> None:
    events: list[tuple[str, int, int]] = []
    result = read_isolated(policy_pdf(extra_pages=1), limits(), lambda *e: events.append(e))
    assert result.page_count == 3
    assert [p.method for p in result.pages] == ["text", "text", "text"]
    assert result.title == "Returns handbook"
    assert events[-1] == ("reading", 3, 3)
    doc = build_document(result.pages)
    assert [o.title for o in doc.outline] == [
        "Returns and Refunds Handbook", "1 Scope", "1.1 Who may ask for a refund",
        "2 Damaged items", "3 Lost parcels", "3.1 Supervisor approval", "Appendix 1",
    ]  # fmt: skip
    assert [o.page for o in doc.outline] == [1, 1, 1, 1, 2, 2, 3]
    assert "internal handbook" not in doc.text  # running header removed
    assert "Page 2" not in doc.text  # page numbers removed
    lost = doc.text.index("A parcel counts as lost")
    assert doc.page_of(lost) == 2


def test_scanned_pages_are_read_with_ocr_up_to_the_limit() -> None:
    data = scanned_pdf([SCAN_PAGE, SCAN_PAGE, SCAN_PAGE])
    events: list[tuple[str, int, int]] = []
    result = read_isolated(data, limits(max_ocr_pages=2), lambda *e: events.append(e))
    assert [p.method for p in result.pages] == ["ocr", "ocr", "skipped"]
    assert result.ocr_skipped == [3]
    assert ("ocr", 2, 2) in events
    doc = build_document(result.pages)
    assert "Orders over fifty pounds are delivered free of charge." in doc.text
    assert doc.outline[0].title == "Delivery charges"


def test_page_limit() -> None:
    result = read_isolated(policy_pdf(extra_pages=3), limits(max_pages=2))
    assert result.page_count == 5
    assert len(result.pages) == 2


def _encrypted() -> bytes:
    buf = io.BytesIO()
    c = Canvas(buf, encrypt="secret")
    c.drawString(72, 720, "Locked")
    c.showPage()
    c.save()
    return buf.getvalue()


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"hello, not a pdf", "not_a_pdf"),
        (b"%PDF-1.7\n1 0 obj << >> garbage", "damaged"),
        (_encrypted(), "encrypted"),
    ],
)
def test_unreadable_files(data: bytes, code: str) -> None:
    with pytest.raises(ReadError) as exc:
        read_isolated(data, limits())
    assert exc.value.code == code
    assert exc.value.message


def test_reader_is_killed_at_the_deadline() -> None:
    with pytest.raises(ReadError) as exc:
        read_isolated(scanned_pdf([SCAN_PAGE] * 3), ReaderLimits(ReadLimits(), timeout_seconds=0.3))
    assert exc.value.code == "timeout"


def test_reader_memory_cap() -> None:
    # 256 MB of address space is not enough to start OCR; the reader reports it cleanly.
    with pytest.raises(ReadError) as exc:
        read_isolated(scanned_pdf([SCAN_PAGE]), ReaderLimits(ReadLimits(), memory_mb=256))
    assert exc.value.code in {"too_complex", "reader_failed"}


def test_typeset_two_column_paper() -> None:
    """A real LaTeX paper (source alongside): columns, hyphenation, headings, two pages."""
    import re
    from pathlib import Path

    data = (Path(__file__).parent / "fixtures" / "two-column-paper.pdf").read_bytes()
    doc = build_document(read_isolated(data, limits()).pages)
    titles = [o.title for o in doc.outline]
    assert titles[0] == "Measuring Delivery Delays in Online Retail"
    assert {"1 Introduction", "2 Data", "2.1 Cleaning", "10 Topic 11", "11 Conclusion"} <= set(
        titles
    )
    # Words hyphenated by TeX at line ends are rejoined, and no sentence on the same page is
    # cut into two paragraphs.
    assert "between January and December" in doc.text
    assert "impossible dates" in doc.text
    sentences = re.findall(r"Sentence \d of topic \d+ [^.]*\.", doc.text)
    whole = [s for s in sentences if s.endswith("seasonal effects observed across the year.")]
    assert len(sentences) == 56
    assert len(whole) >= 55  # one sentence crosses the page break under a running header
    assert doc.page_of(doc.text.index("Topic 11")) == 2
