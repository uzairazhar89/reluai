"""Read a PDF into positioned text lines: the text layer where there is one, OCR where not.

Runs inside the isolated reader process (see ``isolation``), never in the API or worker
process itself, because PDF parsing and OCR operate on untrusted input.

* **Text layer** (PDFium via pypdfium2): each line's text, box, font size and boldness.
  Only a few characters per line are inspected for size and font, so a 60-page document
  takes well under a second.
* **OCR** (PP-OCRv6 small, bundled with the ``rapidocr`` package and run on CPU with ONNX
  Runtime): for pages with no text but with images, i.e. scans. OCR is the slow part, so
  only the first ``max_ocr_pages`` such pages are read; the rest are reported as skipped.

Coordinates are in PDF points, measured from the top-left corner of the page.
"""

from __future__ import annotations

import ctypes
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

PageMethod = Literal["text", "ocr", "empty", "skipped"]
Progress = Callable[[str, int, int], None]

_FORCE_BOLD = 1 << 18  # PDF font descriptor flag 19
_BOLD_NAME = re.compile(r"bold|black|heavy|semibold|demi", re.IGNORECASE)
# PDFium marks a word hyphenated across lines with U+FFFE and joins the two lines; it is
# split back here (as "word-" + next line) so each visual line keeps its own position.
_LINE_BREAK = re.compile(r"\r\n|\r|\n|\ufffe")
_MIN_TEXT_CHARS = 20  # fewer non-space characters than this: treat the page as having no text


class ReadError(Exception):
    """The file cannot be read; ``code`` is stable, ``message`` is shown to the visitor."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class RawLine:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    size: float  # font size in points (OCR: estimated from the line height)
    bold: bool = False


@dataclass(slots=True)
class RawPage:
    number: int  # 1-based
    width: float
    height: float
    method: PageMethod
    lines: list[RawLine] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ReadLimits:
    max_pages: int = 60
    max_ocr_pages: int = 5
    ocr_dpi: int = 150
    ocr_max_pixels: int = 6_000_000
    ocr_threads: int = 2


@dataclass(slots=True)
class ReadResult:
    page_count: int  # pages in the file
    pages: list[RawPage]  # pages read (at most max_pages)
    title: str | None = None
    ocr_skipped: list[int] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "page_count": self.page_count,
            "title": self.title,
            "ocr_skipped": self.ocr_skipped,
            "pages": [
                {
                    "number": p.number,
                    "width": p.width,
                    "height": p.height,
                    "method": p.method,
                    "lines": [asdict(ln) for ln in p.lines],
                }
                for p in self.pages
            ],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> ReadResult:
        return cls(
            page_count=int(data["page_count"]),
            title=data.get("title"),
            ocr_skipped=[int(n) for n in data.get("ocr_skipped", [])],
            pages=[
                RawPage(
                    number=int(p["number"]),
                    width=float(p["width"]),
                    height=float(p["height"]),
                    method=p["method"],
                    lines=[RawLine(**ln) for ln in p["lines"]],
                )
                for p in data["pages"]
            ],
        )


# --------------------------------------------------------------------------- text layer
def _font(textpage: Any, index: int) -> tuple[str, int, int]:
    flags = ctypes.c_int(0)
    needed = pdfium_c.FPDFText_GetFontInfo(textpage, index, None, 0, ctypes.byref(flags))
    name = ""
    if needed > 0:
        buf = ctypes.create_string_buffer(needed)
        pdfium_c.FPDFText_GetFontInfo(textpage, index, buf, needed, ctypes.byref(flags))
        name = buf.value.decode("utf-8", "replace")
    weight = int(pdfium_c.FPDFText_GetFontWeight(textpage, index))
    return name, flags.value, weight


_PROBES = 7  # characters sampled per line for size, weight and baseline


def _line(textpage: Any, text: str, first: int, last: int, height: float) -> RawLine | None:
    """Box, font size and boldness of one line, from a few of its (non-space) characters.

    Sampling several characters matters: PDFium reports generated spaces with size 1, and a
    single sample can land on a small-caps keyword in an ordinary sentence.
    """
    raw = textpage.raw
    visible = [i for i in range(first, last + 1) if not text[i].isspace()]
    if not visible:
        return None
    step = max(1, len(visible) // _PROBES)
    probes = visible[::step][:_PROBES]
    sizes = sorted(
        s for s in (float(pdfium_c.FPDFText_GetFontSize(raw, i)) for i in probes) if s > 2
    )
    size = sizes[len(sizes) // 2] if sizes else 10.0
    bold_votes = 0
    for i in probes:
        name, flags, weight = _font(raw, i)
        if weight >= 600 or flags & _FORCE_BOLD or _BOLD_NAME.search(name):
            bold_votes += 1
    anchor = probes[len(probes) // 2]
    ox, oy = ctypes.c_double(0), ctypes.c_double(0)
    if pdfium_c.FPDFText_GetCharOrigin(raw, anchor, ctypes.byref(ox), ctypes.byref(oy)):
        baseline = height - oy.value
    else:
        baseline = height - textpage.get_charbox(anchor)[1]
    left = textpage.get_charbox(visible[0])[0]
    right = textpage.get_charbox(visible[-1])[2]
    # The line box is derived from the baseline and font size, so every line of the same
    # size has the same height whatever its letters.
    return RawLine(
        text=text[first : last + 1].strip(),
        x0=round(min(left, right), 1),
        top=round(baseline - 0.8 * size, 1),
        x1=round(max(left, right), 1),
        bottom=round(baseline + 0.2 * size, 1),
        size=round(size, 2),
        bold=bold_votes * 2 > len(probes),
    )


def _text_lines(page: pdfium.PdfPage, height: float) -> list[RawLine]:
    textpage = page.get_textpage()
    try:
        count = textpage.count_chars()
        if count <= 0:
            return []
        text = textpage.get_text_range(0, count)
        lines: list[RawLine] = []
        start = 0
        for m in [*_LINE_BREAK.finditer(text), None]:
            end = min(m.start() if m else len(text), count)
            line = _line(textpage, text, start, end - 1, height) if end > start else None
            if line is not None:
                if m is not None and m.group(0) == "\ufffe":
                    line = RawLine(f"{line.text}-", line.x0, line.top, line.x1, line.bottom,
                                   line.size, line.bold)  # fmt: skip
                lines.append(line)
            if m is None:
                break
            start = m.end()
        return lines
    finally:
        textpage.close()


def _has_images(page: pdfium.PdfPage) -> bool:
    for _ in page.get_objects(filter=[pdfium_c.FPDF_PAGEOBJ_IMAGE], max_depth=2):
        return True
    return False


# --------------------------------------------------------------------------- OCR
class _Ocr:
    """Lazily created: importing ONNX Runtime and OpenCV costs about a second."""

    def __init__(self, threads: int) -> None:
        self.threads = threads
        self._engine: Any = None

    def __call__(self, image: Any) -> Any:
        if self._engine is None:
            from rapidocr import RapidOCR

            self._engine = RapidOCR(
                params={
                    "Global.log_level": "error",
                    "EngineConfig.onnxruntime.intra_op_num_threads": self.threads,
                    "EngineConfig.onnxruntime.inter_op_num_threads": 1,
                }
            )
        return self._engine(image)


def _ocr_lines(page: pdfium.PdfPage, limits: ReadLimits, ocr: _Ocr) -> list[RawLine]:
    import numpy as np

    width, height = page.get_size()
    scale = limits.ocr_dpi / 72
    pixels = width * scale * height * scale
    if pixels > limits.ocr_max_pixels:
        scale *= (limits.ocr_max_pixels / pixels) ** 0.5
    bitmap = page.render(scale=scale, grayscale=False)
    try:
        image = np.ascontiguousarray(bitmap.to_pil().convert("RGB"))
    finally:
        bitmap.close()
    result = ocr(image)
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []
    words: list[RawLine] = []
    for box, text, score in zip(boxes, result.txts, result.scores, strict=False):
        if not text or not text.strip() or float(score) < 0.5:
            continue
        xs = [float(p[0]) / scale for p in box]
        ys = [float(p[1]) / scale for p in box]
        top, bottom = min(ys), max(ys)
        words.append(
            RawLine(
                text=" ".join(str(text).split()),
                x0=round(min(xs), 1),
                top=round(top, 1),
                x1=round(max(xs), 1),
                bottom=round(bottom, 1),
                # A detected text line is about 1.2x the font size tall.
                size=round((bottom - top) / 1.2, 2),
            )
        )
    return _merge_rows(words)


def _merge_rows(boxes: list[RawLine]) -> list[RawLine]:
    """Join OCR boxes that sit on the same row into one line, left to right."""
    rows: list[list[RawLine]] = []
    for b in sorted(boxes, key=lambda b: (b.top, b.x0)):
        if rows:
            row = rows[-1]
            ref = row[0]
            overlap = min(ref.bottom, b.bottom) - max(ref.top, b.top)
            if overlap >= 0.5 * min(ref.bottom - ref.top, b.bottom - b.top):
                row.append(b)
                continue
        rows.append([b])
    out: list[RawLine] = []
    for row in rows:
        row.sort(key=lambda b: b.x0)
        out.append(
            RawLine(
                text=" ".join(b.text for b in row),
                x0=min(b.x0 for b in row),
                top=min(b.top for b in row),
                x1=max(b.x1 for b in row),
                bottom=max(b.bottom for b in row),
                size=max(b.size for b in row),
            )
        )
    return out


# --------------------------------------------------------------------------- document
def _title(pdf: pdfium.PdfDocument) -> str | None:
    try:
        meta = pdf.get_metadata_dict(skip_empty=True)
    except Exception:
        return None
    title = " ".join(str(meta.get("Title", "")).split())
    return title[:200] or None


def _ocr_pages(
    pdf: pdfium.PdfDocument,
    result: ReadResult,
    scanned: list[int],
    limits: ReadLimits,
    progress: Progress | None,
) -> None:
    """OCR the first ``max_ocr_pages`` scanned pages; list the rest as skipped."""
    todo = scanned[: limits.max_ocr_pages]
    result.ocr_skipped = [i + 1 for i in scanned[limits.max_ocr_pages :]]
    ocr = _Ocr(limits.ocr_threads)
    for done, index in enumerate(todo):
        if progress:
            progress("ocr", done, len(todo))
        page = pdf[index]
        try:
            result.pages[index].lines = _ocr_lines(page, limits, ocr)
            result.pages[index].method = "ocr"
        finally:
            page.close()
    if todo and progress:
        progress("ocr", len(todo), len(todo))


def read_pdf(data: bytes, limits: ReadLimits, progress: Progress | None = None) -> ReadResult:
    """Positioned lines for each page; raises ``ReadError`` for unreadable files."""
    if b"%PDF-" not in data[:1024]:  # the header may follow a little junk, as readers allow
        raise ReadError("not_a_pdf", "This file is not a PDF.")
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as exc:
        if "password" in str(exc).lower():
            raise ReadError(
                "encrypted", "This PDF is password-protected; upload an unlocked copy."
            ) from exc
        raise ReadError("damaged", "This PDF is damaged or uses an unsupported format.") from exc
    try:
        page_count = len(pdf)
        if page_count == 0:
            raise ReadError("no_pages", "This PDF has no pages.")
        result = ReadResult(page_count=page_count, pages=[], title=_title(pdf))
        to_read = min(page_count, limits.max_pages)
        scanned: list[int] = []  # indexes of pages with images but no text
        for index in range(to_read):
            if progress:
                progress("reading", index, to_read)
            page = pdf[index]
            try:
                width, height = page.get_size()
                lines = _text_lines(page, height)
                chars = sum(len(ln.text.replace(" ", "")) for ln in lines)
                method: PageMethod = "text" if chars else "empty"
                if chars < _MIN_TEXT_CHARS and _has_images(page):
                    scanned.append(index)
                    method, lines = "skipped", []
                result.pages.append(
                    RawPage(index + 1, round(width, 1), round(height, 1), method, lines)
                )
            finally:
                page.close()
        if progress:
            progress("reading", to_read, to_read)
        _ocr_pages(pdf, result, scanned, limits, progress)
        return result
    finally:
        pdf.close()
