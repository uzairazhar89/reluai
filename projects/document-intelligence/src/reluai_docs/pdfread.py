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

For invoice extraction the reader can also return **segments**: pieces of a line separated
by a wide gap (table cells, a label and its value), from character boxes on the text layer
and from the individual detected boxes with OCR. It can also return a small JPEG preview of
the first pages, so pages of an untrusted PDF are rendered here, not in the API process.
"""

from __future__ import annotations

import base64
import ctypes
import io
import math
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
    segments: list[RawLine] = field(default_factory=list)  # only when requested
    preview: str | None = None  # base64 JPEG, only when requested


@dataclass(frozen=True, slots=True)
class ReadLimits:
    max_pages: int = 60
    max_ocr_pages: int = 5
    ocr_dpi: int = 150
    ocr_max_pixels: int = 6_000_000
    ocr_threads: int = 2
    segments: bool = False
    preview_pages: int = 0
    preview_dpi: int = 100


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
                    "segments": [asdict(sg) for sg in p.segments],
                    "preview": p.preview,
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
                    segments=[RawLine(**sg) for sg in p.get("segments", [])],
                    preview=p.get("preview"),
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


def _segments(
    textpage: Any, text: str, span: tuple[int, int], height: float, size: float
) -> list[RawLine]:
    """Split one line into segments (table cells, a label and its value).

    The PDF says which spaces are real: text drawn separately (each table cell) is joined
    by spaces PDFium generates, while a space inside a description is in the file. So a
    break is a gap bridged only by generated spaces and wider than a word space, or any
    gap wider than one and a half times the font size, or three or more real spaces in a
    row (columns aligned with spaces).
    """
    first, last = span
    raw = textpage.raw
    out: list[RawLine] = []
    start: int | None = None
    prev = first
    prev_right: float | None = None
    real_spaces = 0
    for i in range(first, last + 1):
        if text[i].isspace():
            if not pdfium_c.FPDFText_IsGenerated(raw, i):
                real_spaces += 1
            continue
        left, _bottom, right, _top = textpage.get_charbox(i)
        if start is not None and prev_right is not None:
            gap = left - prev_right
            generated = real_spaces == 0
            if (
                (generated and gap > max(2.5, 0.45 * size))
                or gap > max(3.0, 1.5 * size)
                or real_spaces >= 3
            ):
                seg = _line(textpage, text, start, prev, height)
                if seg is not None:
                    out.append(seg)
                start = None
        if start is None:
            start = i
        prev, prev_right, real_spaces = i, right, 0
    if start is not None:
        seg = _line(textpage, text, start, prev, height)
        if seg is not None:
            out.append(seg)
    return out


def _text_lines(
    page: pdfium.PdfPage, height: float, *, segments: bool = False
) -> tuple[list[RawLine], list[RawLine]]:
    textpage = page.get_textpage()
    try:
        count = textpage.count_chars()
        if count <= 0:
            return [], []
        text = textpage.get_text_range(0, count)
        lines: list[RawLine] = []
        segs: list[RawLine] = []
        start = 0
        for m in [*_LINE_BREAK.finditer(text), None]:
            end = min(m.start() if m else len(text), count)
            line = _line(textpage, text, start, end - 1, height) if end > start else None
            if line is not None:
                if m is not None and m.group(0) == "\ufffe":
                    line = RawLine(f"{line.text}-", line.x0, line.top, line.x1, line.bottom,
                                   line.size, line.bold)  # fmt: skip
                lines.append(line)
                if segments:
                    segs += _segments(textpage, text, (start, end - 1), height, line.size)
            if m is None:
                break
            start = m.end()
        return lines, segs
    finally:
        textpage.close()


def _preview(page: pdfium.PdfPage, dpi: int) -> str:
    bitmap = page.render(scale=dpi / 72, grayscale=True)
    try:
        image = bitmap.to_pil().convert("L")
    finally:
        bitmap.close()
    buf = io.BytesIO()
    image.save(buf, "JPEG", quality=80, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("ascii")


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


def _ocr_lines(
    page: pdfium.PdfPage, limits: ReadLimits, ocr: _Ocr
) -> tuple[list[RawLine], list[RawLine]]:
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
        return [], []
    found = [
        ([(float(p[0]) / scale, float(p[1]) / scale) for p in box], " ".join(str(text).split()))
        for box, text, score in zip(boxes, result.txts, result.scores, strict=False)
        if text and str(text).strip() and float(score) >= 0.5
    ]
    found = _deskew(found, width / 2, height / 2)
    words: list[RawLine] = []
    for points, text in found:
        xs = [x for x, _ in points]
        ys = [y for _, y in points]
        top, bottom = min(ys), max(ys)
        words.append(
            RawLine(
                text=text,
                x0=round(min(xs), 1),
                top=round(top, 1),
                x1=round(max(xs), 1),
                bottom=round(bottom, 1),
                # A detected text line is about 1.2x the font size tall.
                size=round((bottom - top) / 1.2, 2),
            )
        )
    return _merge_rows(words), words if limits.segments else []


Points = list[tuple[float, float]]


def _deskew(found: list[tuple[Points, str]], cx: float, cy: float) -> list[tuple[Points, str]]:
    """Undo a scan's rotation in the coordinates: the detector's boxes follow the text, so
    the median slope of the long boxes is the page's skew. Without this, a row of a table
    drifts by several points from one side of the page to the other."""
    slopes = sorted(
        math.atan2(p[1][1] - p[0][1], p[1][0] - p[0][0])
        for p, _ in found
        if len(p) == 4 and abs(p[1][0] - p[0][0]) > 3 * abs(p[3][1] - p[0][1]) > 0
    )
    if len(slopes) < 3:
        return found
    angle = slopes[len(slopes) // 2]
    if abs(angle) < math.radians(0.1):
        return found
    cos, sin = math.cos(angle), math.sin(angle)
    return [
        (
            [
                (cx + (x - cx) * cos + (y - cy) * sin, cy - (x - cx) * sin + (y - cy) * cos)
                for x, y in points
            ],
            text,
        )
        for points, text in found
    ]


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
            target = result.pages[index]
            target.lines, target.segments = _ocr_lines(page, limits, ocr)
            target.method = "ocr"
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
                lines, segs = _text_lines(page, height, segments=limits.segments)
                chars = sum(len(ln.text.replace(" ", "")) for ln in lines)
                method: PageMethod = "text" if chars else "empty"
                if chars < _MIN_TEXT_CHARS and _has_images(page):
                    scanned.append(index)
                    method, lines, segs = "skipped", [], []
                preview = None
                if index < limits.preview_pages:
                    preview = _preview(page, limits.preview_dpi)
                result.pages.append(
                    RawPage(
                        number=index + 1,
                        width=round(width, 1),
                        height=round(height, 1),
                        method=method,
                        lines=lines,
                        segments=segs,
                        preview=preview,
                    )
                )
            finally:
                page.close()
        if progress:
            progress("reading", to_read, to_read)
        _ocr_pages(pdf, result, scanned, limits, progress)
        return result
    finally:
        pdf.close()
