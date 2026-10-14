"""Read an invoice's fields, line items and total from positioned text segments.

The input is what the reader returns with ``segments=True``: pieces of text with their
boxes, from the text layer or from OCR. Nothing here depends on how the invoice was drawn;
the steps are the ones a person uses to read an unfamiliar invoice:

1. **Rows**: segments at the same height form a row (scans are deskewed by the reader).
2. **The table**: its header row is the one naming several columns ("Qty", "Unit price",
   ...). When the wording is unfamiliar, the header is the row above the first row that
   looks like an item (a whole number, amounts with pence and some text).
3. **Columns**: each header cell owns the horizontal band up to halfway to its neighbours;
   a segment belongs to the column whose band holds its centre. A column whose header is
   not recognised gets its role from its content: whole numbers are quantities, the
   longest text is the description, and of two money columns the amount is the one that
   equals quantity × the other.
4. **Items** run from the header to the totals; a row with only description text is a
   wrapped description; on later pages the table resumes under the repeated header.
5. **Header fields** come from labels ("Invoice no.", "Date", ...) and the value beside or
   below them; a field whose label is not recognised is taken by elimination from the
   remaining label/value pairs, by the type of its value.
6. **Checks**: every line's quantity × unit price must equal its amount, the amounts must
   add up to the total, and the header must have a number and a date. A failed check marks
   the result for review; it is never silently "fixed".

The vocabulary below was written from the layouts used during development; the evaluation
also runs on layouts with wordings it does not contain.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from itertools import pairwise
from typing import Any, Literal

from reluai_docs.pdfread import RawPage

Role = Literal["code", "description", "quantity", "unit_price", "amount"]
HeaderField = Literal["number", "date", "customer", "country"]
ROLES: tuple[Role, ...] = ("code", "description", "quantity", "unit_price", "amount")
FIELDS: tuple[HeaderField, ...] = ("number", "date", "customer", "country")

_LABELS: dict[HeaderField, set[str]] = {
    "number": {"invoice no", "invoice number", "invoice #", "number", "no",
               "credit note no", "credit note number", "credit note #"},
    "date": {"date", "invoice date", "credit note date", "issued", "date of issue"},
    "customer": {"customer", "customer id", "customer no", "account"},
    "country": {"country", "ship to", "delivery country"},
}  # fmt: skip
_HEADERS: dict[Role, set[str]] = {
    "code": {"code", "stock code", "item", "sku"},
    "description": {"description", "item description", "product"},
    "quantity": {"qty", "quantity", "units"},
    "unit_price": {"unit price", "price", "unit cost"},
    "amount": {"amount", "total", "line total"},
}
_TOTALS = {"total", "total due", "amount due", "invoice total"}
_SUBTOTAL = "subtotal"
_ITEMS = {"items", "item count", "number of items"}

_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%d.%m.%Y", "%d-%b-%Y")
_MONEY = re.compile(r"\d{1,3}(?:,\d{3})+\.\d{2}|\d+\.\d{2}")
_INT = re.compile(r"\d{1,3}(?:,\d{3})+|\d+")
_PAGE_FOOTER = re.compile(r"^page \d+ of \d+$|^portfolio demonstration", re.IGNORECASE)
_MINUS = "-−–"


# --------------------------------------------------------------------------- parsing
def _norm(text: str) -> str:
    t = text.lower().replace("(gbp)", "").replace("£", "")
    t = t.strip().rstrip(":").strip().rstrip(".")
    return " ".join(t.replace(".", " ").split())


def parse_money(text: str) -> Decimal | None:
    t = text.replace(" ", "")
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    if t[:1] and t[0] in _MINUS:
        neg, t = True, t[1:]
    t = t.removeprefix("£").removeprefix("GBP")
    if t[:1] and t[0] in _MINUS:
        neg, t = True, t[1:]
    if not _MONEY.fullmatch(t):
        return None
    value = Decimal(t.replace(",", ""))
    return -value if neg else value


def parse_quantity(text: str) -> int | None:
    t = text.replace(" ", "")
    neg = False
    if t.startswith("(") and t.endswith(")"):
        neg, t = True, t[1:-1]
    if t[:1] and t[0] in _MINUS:
        neg, t = True, t[1:]
    if not _INT.fullmatch(t):
        return None
    value = int(t.replace(",", ""))
    return -value if neg else value


def parse_date(text: str) -> datetime | None:
    t = " ".join(text.split())
    for fmt in _DATE_FORMATS:
        for full in (fmt, f"{fmt} %H:%M"):
            try:
                return datetime.strptime(t, full)  # noqa: DTZ007 - dates as printed
            except ValueError:
                continue
    return None


# --------------------------------------------------------------------------- geometry
@dataclass(frozen=True, slots=True)
class Box:
    page: int
    x0: float
    top: float
    x1: float
    bottom: float

    def to_json(self) -> dict[str, float | int]:
        return {"page": self.page, "x0": self.x0, "top": self.top, "x1": self.x1,
                "bottom": self.bottom}  # fmt: skip

    @staticmethod
    def around(segs: Sequence[Seg]) -> Box | None:
        if not segs:
            return None
        return Box(
            segs[0].page,
            round(min(s.x0 for s in segs), 1),
            round(min(s.top for s in segs), 1),
            round(max(s.x1 for s in segs), 1),
            round(max(s.bottom for s in segs), 1),
        )


@dataclass(frozen=True, slots=True)
class Seg:
    page: int
    text: str
    x0: float
    top: float
    x1: float
    bottom: float
    bold: bool

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def height(self) -> float:
        return max(1.0, self.bottom - self.top)


@dataclass(slots=True)
class Row:
    page: int
    segs: list[Seg]

    @property
    def top(self) -> float:
        return min(s.top for s in self.segs)

    @property
    def bottom(self) -> float:
        return max(s.bottom for s in self.segs)

    @property
    def cy(self) -> float:
        return sum(s.cy for s in self.segs) / len(self.segs)

    @property
    def height(self) -> float:
        return sorted(s.height for s in self.segs)[len(self.segs) // 2]

    @property
    def text(self) -> str:
        return " ".join(s.text for s in self.segs)


def rows_of(pages: Sequence[RawPage]) -> list[Row]:
    """Group each page's segments into rows, top to bottom, each row left to right."""
    out: list[Row] = []
    for page in pages:
        segs = sorted(
            (Seg(page.number, s.text, s.x0, s.top, s.x1, s.bottom, s.bold)
             for s in page.segments if s.text.strip()),
            key=lambda s: s.cy,
        )  # fmt: skip
        rows: list[Row] = []
        for s in segs:
            if rows:
                row = rows[-1]
                if abs(s.cy - row.cy) < 0.45 * max(row.height, s.height):
                    row.segs.append(s)
                    continue
            rows.append(Row(page.number, [s]))
        for row in rows:
            row.segs.sort(key=lambda s: s.x0)
        out += rows
    return out


# --------------------------------------------------------------------------- results
@dataclass(slots=True)
class FieldValue:
    value: Any = None  # str, int, datetime or Decimal
    text: str | None = None  # as printed
    box: Box | None = None
    label: str | None = None  # the label it was found by, as printed
    by: Literal["label", "elimination", "table", "fallback", "missing"] = "missing"

    def to_json(self) -> dict[str, Any]:
        value = self.value
        if isinstance(value, datetime):
            value = value.isoformat(timespec="minutes")
        elif isinstance(value, Decimal):
            value = str(value)
        return {
            "value": value,
            "text": self.text,
            "box": self.box.to_json() if self.box else None,
            "label": self.label,
            "by": self.by,
        }


@dataclass(slots=True)
class ExtractedLine:
    cells: dict[Role, str]  # text per column, as printed
    box: Box | None
    stock_code: str | None = None
    description: str | None = None
    quantity: int | None = None
    unit_price: Decimal | None = None
    amount: Decimal | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "description": self.description,
            "quantity": self.quantity,
            "unit_price": None if self.unit_price is None else str(self.unit_price),
            "amount": None if self.amount is None else str(self.amount),
            "cells": self.cells,
            "box": self.box.to_json() if self.box else None,
        }


@dataclass(frozen=True, slots=True)
class Check:
    name: str
    passed: bool
    detail: str

    def to_json(self) -> dict[str, Any]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(slots=True)
class Column:
    x0: float
    x1: float
    header: str
    role: Role | None
    by: Literal["header", "content", "none"] = "none"


@dataclass(slots=True)
class Extraction:
    document_type: Literal["invoice", "credit_note"] | None = None
    fields: dict[HeaderField, FieldValue] = field(default_factory=dict)
    total: FieldValue = field(default_factory=FieldValue)
    subtotal: FieldValue | None = None
    item_count: int | None = None
    lines: list[ExtractedLine] = field(default_factory=list)
    columns: list[Column] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return not self.checks or not all(c.passed for c in self.checks)

    def to_json(self) -> dict[str, Any]:
        return {
            "document_type": self.document_type,
            "fields": {k: v.to_json() for k, v in self.fields.items()},
            "total": self.total.to_json(),
            "subtotal": self.subtotal.to_json() if self.subtotal else None,
            "item_count": self.item_count,
            "lines": [ln.to_json() for ln in self.lines],
            "columns": [
                {"header": c.header, "role": c.role, "by": c.by, "x0": c.x0, "x1": c.x1}
                for c in self.columns
            ],
            "checks": [c.to_json() for c in self.checks],
            "needs_review": self.needs_review,
            "notes": self.notes,
        }


# --------------------------------------------------------------------------- the table
def _header_role(text: str) -> Role | None:
    n = _norm(text)
    for role in ROLES:
        if n in _HEADERS[role]:
            return role
    return None


def _split_merged(seg: Seg) -> list[tuple[Seg, Role | None]]:
    """A header cell that holds two known headers ("Unit price Line total", when the gap
    between them was too narrow to split) is divided at the word boundary."""
    whole = _header_role(seg.text)
    if whole:
        return [(seg, whole)]
    words = seg.text.split()
    cuts: list[tuple[str, str, Role, Role]] = []
    for cut in range(1, len(words)):
        left, right = " ".join(words[:cut]), " ".join(words[cut:])
        a, b = _header_role(left), _header_role(right)
        if a and b and a != b:
            cuts.append((left, right, a, b))
    if not cuts:
        return [(seg, None)]
    # "Unit price (GBP) | Line total (GBP)", not "Unit price | (GBP) Line total (GBP)".
    left, right, a, b = min(cuts, key=lambda c: (c[1].startswith("("), abs(len(c[0]) - len(c[1]))))
    x = seg.x0 + (seg.x1 - seg.x0) * len(left) / max(1, len(seg.text))
    return [
        (Seg(seg.page, left, seg.x0, seg.top, x - 2, seg.bottom, seg.bold), a),
        (Seg(seg.page, right, x + 2, seg.top, seg.x1, seg.bottom, seg.bold), b),
    ]


def _header_cells(row: Row) -> list[tuple[Seg, Role | None]]:
    """The header's cells with their roles: cells holding two headers are split, and
    neighbours that only make a header together ("Stock" "code", "Amount" "(GBP)", as OCR
    sometimes returns them) are joined."""
    cells = [cell for s in row.segs for cell in _split_merged(s)]
    out: list[tuple[Seg, Role | None]] = []
    for seg, role in cells:
        if out:
            prev, prev_role = out[-1]
            joined = f"{prev.text} {seg.text}"
            close = seg.x0 - prev.x1 < 1.5 * max(prev.height, seg.height)
            if close and (role is None or prev_role is None) and _header_role(joined):
                merged = Seg(seg.page, joined, prev.x0, min(prev.top, seg.top), seg.x1,
                             max(prev.bottom, seg.bottom), prev.bold)  # fmt: skip
                out[-1] = (merged, _header_role(joined))
                continue
        out.append((seg, role))
    return out


def _looks_like_item(row: Row) -> bool:
    money = sum(parse_money(s.text) is not None for s in row.segs)
    ints = sum(parse_quantity(s.text) is not None for s in row.segs)
    words = sum(bool(re.search(r"[A-Za-z]{2}", s.text)) for s in row.segs)
    return money >= 1 and ints >= 1 and words >= 1 and len(row.segs) >= 3


def _find_header(rows: Sequence[Row]) -> int | None:
    """Index of the table's header row: named columns, or the row above the first item."""
    for i, row in enumerate(rows):
        roles = {r for _, r in _header_cells(row) if r}
        numeric = roles & {"quantity", "unit_price", "amount"}
        if len(roles) >= 3 and numeric and roles & {"code", "description"}:
            return i
    for i, row in enumerate(rows):
        if _looks_like_item(row):
            for j in range(i - 1, max(-1, i - 3), -1):
                above = rows[j]
                if (
                    above.page == row.page
                    and len(above.segs) >= 3
                    and not any(parse_money(s.text) is not None for s in above.segs)
                    and row.top - above.bottom < 4 * row.height
                ):
                    return j
            return None
    return None


def _columns(row: Row) -> list[Column]:
    cols: list[Column] = []
    for seg, role in _header_cells(row):
        cols.append(Column(seg.x0, seg.x1, seg.text, role, "header" if role else "none"))
    cols.sort(key=lambda c: c.x0)
    seen: set[Role] = set()
    for c in cols:  # a role named twice: keep the first, decide the other by content
        if c.role in seen:
            c.role, c.by = None, "none"
        elif c.role:
            seen.add(c.role)
    return cols


def _bands(cols: Sequence[Column], body: Sequence[Row]) -> list[tuple[float, float]]:
    """Each column's horizontal band. The boundary between two columns is the emptiest
    vertical strip of the table body between them (the gutter): a header can be much
    shorter than its column ("Description" over long descriptions), so the midpoint
    between headers is not enough. It must lie between the two header cells (a column
    boundary never cuts through a header); among equally empty strips, the one nearest
    the middle of that gap wins."""
    occupied: Counter[int] = Counter()
    for row in body:
        for seg in row.segs:
            for x in range(int(seg.x0), int(seg.x1) + 1):
                occupied[x] += 1
    edges: list[float] = []
    for a, b in pairwise(cols):
        lo, hi = int(a.x1), int(b.x0) + 1
        mid = (a.x1 + b.x0) / 2
        if hi <= lo:
            edges.append(mid)
            continue
        edges.append(float(min(range(lo, hi + 1), key=lambda x: (occupied[x], abs(x - mid)))))
    bounds = [float("-inf"), *edges, float("inf")]
    return list(pairwise(bounds))


def _band_of(x: float, bands: Sequence[tuple[float, float]]) -> int:
    return next(i for i, (lo, hi) in enumerate(bands) if lo <= x < hi)


def _split_across(seg: Seg, bands: Sequence[tuple[float, float]]) -> list[Seg]:
    """A segment that spans two columns (OCR joins a right-aligned quantity to the
    description beside it: "6 PINK HAPPY BUNTING") is cut at the word that crosses the
    boundary; word positions are estimated from character positions."""
    first, last = _band_of(seg.x0 + 1, bands), _band_of(seg.x1 - 1, bands)
    words = seg.text.split()
    if first == last or len(words) < 2:
        return [seg]
    width = (seg.x1 - seg.x0) / max(1, len(seg.text))
    pieces: list[tuple[int, list[str], float, float]] = []
    pos = 0
    for w in words:
        start = seg.text.index(w, pos)
        pos = start + len(w)
        x0, x1 = seg.x0 + start * width, seg.x0 + pos * width
        band = _band_of((x0 + x1) / 2, bands)
        if pieces and pieces[-1][0] == band:
            pieces[-1][1].append(w)
            pieces[-1] = (band, pieces[-1][1], pieces[-1][2], x1)
        else:
            pieces.append((band, [w], x0, x1))
    return [
        Seg(seg.page, " ".join(ws), round(x0, 1), seg.top, round(x1, 1), seg.bottom, seg.bold)
        for _band, ws, x0, x1 in pieces
    ]


def _cells(row: Row, bands: Sequence[tuple[float, float]]) -> list[list[Seg]]:
    out: list[list[Seg]] = [[] for _ in bands]
    for seg in row.segs:
        for piece in _split_across(seg, bands):
            out[_band_of(piece.cx, bands)].append(piece)
    return out


def cell_text(segs: Sequence[Seg]) -> str:
    """A cell's text in reading order: its segments grouped into visual lines (a wrapped
    description has several), each line left to right. Sorting by position alone would
    scramble OCR words whose boxes sit a point higher or lower than their neighbours."""
    lines: list[list[Seg]] = []
    for seg in sorted(segs, key=lambda s: s.cy):
        if lines and abs(seg.cy - sum(s.cy for s in lines[-1]) / len(lines[-1])) < 0.5 * seg.height:
            lines[-1].append(seg)
        else:
            lines.append([seg])
    return " ".join(s.text for line in lines for s in sorted(line, key=lambda s: s.x0))


def _is_footer(row: Row) -> bool:
    return any(_PAGE_FOOTER.search(s.text.strip()) for s in row.segs)


def _row_label(row: Row) -> str:
    """The row's words without its numbers: "Total due £78.90" → "total due"."""
    return _norm(" ".join(
        s.text for s in row.segs
        if parse_money(s.text) is None and parse_quantity(s.text) is None
    ))  # fmt: skip


def _is_totals(row: Row) -> bool:
    label = _row_label(row)
    return label in _TOTALS or label == _SUBTOTAL or label in _ITEMS


def _kind(cells: Sequence[str]) -> str:
    cells = [t for t in cells if t]
    if not cells:
        return "empty"

    def share(test: Any) -> float:
        return sum(1 for t in cells if test(t)) / len(cells)

    if share(lambda t: parse_quantity(t) is not None) > 0.8:
        return "int"
    if share(lambda t: parse_money(t) is not None) > 0.8:
        return "money"
    if share(lambda t: re.search(r"[A-Za-z]{3}", t) and " " in t) > 0.5:
        return "text"
    return "code"


def _holds(table: Sequence[Sequence[str]], q: int, p: int, a: int) -> float:
    """Share of rows where quantity × unit price = amount, with these columns."""
    good = total = 0
    for row in table:
        qty, price, amount = parse_quantity(row[q]), parse_money(row[p]), parse_money(row[a])
        if qty is None or price is None or amount is None:
            continue
        total += 1
        good += abs(qty * price - amount) < Decimal("0.005")
    return good / total if total else 0.0


def _assign_by_content(  # noqa: PLR0912 - one decision per role, in order
    cols: list[Column], table: list[list[str]], notes: list[str]
) -> None:
    """Give columns without a recognised header a role from what they contain: quantity,
    unit price and amount are the three columns where quantity × price = amount on most
    rows (the amount is the right-hand one when both ways round fit, as when every
    quantity is one); the longest text column is the description; what is left is the
    code."""
    if not table:
        return
    unknown = [i for i, c in enumerate(cols) if c.role is None]
    if not unknown:
        return
    kind = {i: _kind([row[i] for row in table]) for i in unknown}

    def options(role: Role, want: str) -> list[int]:
        known = [i for i, c in enumerate(cols) if c.role == role]
        return known or [i for i in unknown if kind[i] == want]

    taken: dict[int, Role] = {}
    best: tuple[tuple[float, bool], int, int, int] | None = None
    for q in options("quantity", "int"):
        for p in options("unit_price", "money"):
            for a in options("amount", "money"):
                if len({q, p, a}) == 3:
                    key = (_holds(table, q, p, a), a > p)
                    if best is None or key > best[0]:
                        best = (key, q, p, a)
    if best is not None and best[0][0] >= 0.8:
        _, q, p, a = best
        triple: tuple[tuple[int, Role], ...] = ((q, "quantity"), (p, "unit_price"), (a, "amount"))
        taken.update({i: r for i, r in triple if cols[i].role is None})
    present = {c.role for c in cols} | set(taken.values())
    rest = [i for i in unknown if i not in taken]
    texts = [i for i in rest if kind[i] == "text"]
    if "description" not in present and texts:
        i = max(texts, key=lambda i: sum(len(r[i]) for r in table))
        taken[i] = "description"
        rest.remove(i)
    if "quantity" not in present and "quantity" not in taken.values():
        ints = [i for i in rest if kind[i] == "int"]
        if len(ints) == 1 and "code" in present:
            taken[ints[0]] = "quantity"
            rest.remove(ints[0])
    codes = [i for i in rest if kind[i] in ("code", "int")]
    if "code" not in present and codes:
        taken[codes[0]] = "code"
    for i, role in taken.items():
        cols[i].role, cols[i].by = role, "content"
        notes.append(f"Column “{cols[i].header}” read as {role.replace('_', ' ')} "
                     "from its content")  # fmt: skip


def _header_matches(row: Row, header_texts: set[str]) -> int:
    return sum(_norm(seg.text) in header_texts for seg, _ in _header_cells(row))


def _body(rows: Sequence[Row], head: int) -> list[Row]:
    """The rows under the header on its page, up to the totals or the page footer."""
    body: list[Row] = []
    for row in rows[head + 1 : head + 80]:
        if row.page != rows[head].page or _is_totals(row) or _is_footer(row):
            break
        body.append(row)
    return body


def _read_table(
    rows: list[Row], start: int, cols: list[Column], bands: list[tuple[float, float]]
) -> tuple[list[list[list[Seg]]], int]:
    """Item rows (as segments per column) and the index of the first row after the table
    (the totals, when there are any)."""
    header_texts = {_norm(c.header) for c in cols}
    text_cols = {k for k, c in enumerate(cols) if c.role in ("description", None)}
    items: list[list[list[Seg]]] = []
    item_rows: list[Row] = []
    paused: int | None = None  # the page on which the table stopped, waiting to resume
    i = start + 1
    while i < len(rows):
        row = rows[i]
        if _is_totals(row):
            break
        money = sum(1 for seg in row.segs if parse_money(seg.text) is not None)
        if items and money == 1 and len(row.segs) <= 3 and not _looks_like_item(row):
            break  # a label and one amount: a totals row with a wording not recognised
        if paused is not None:
            if row.page > paused and _header_matches(row, header_texts) >= max(
                2, len(header_texts) - 1
            ):
                paused = None  # the repeated header on a later page
            i += 1
            continue
        if _is_footer(row):
            paused = row.page
            i += 1
            continue
        cells = _cells(row, bands)
        filled = sum(1 for c in cells if c)
        if filled >= 3 or (filled >= 2 and _looks_like_item(row)):
            items.append(cells)
            item_rows.append(row)
        elif items and filled and all(k in text_cols for k, c in enumerate(cells) if c):
            prev = items[-1]
            last_bottom = max(seg.bottom for c in prev for seg in c)
            if row.page == item_rows[-1].page and row.top - last_bottom < 1.6 * row.height:
                for k, c in enumerate(cells):
                    prev[k] = prev[k] + c  # a wrapped description
            else:
                paused = row.page
        elif items:
            paused = row.page  # a note or footer: the table may resume on the next page
        i += 1
    return items, i


# --------------------------------------------------------------------------- header fields
def _label_field(text: str) -> HeaderField | None:
    n = _norm(text)
    for f in FIELDS:
        if n in _LABELS[f]:
            return f
    return None


def _inline(seg: Seg) -> tuple[HeaderField, str, str] | None:
    """A label and value in one segment: "Invoice no.: 489434"."""
    words = seg.text.split()
    for cut in range(1, min(len(words), 5)):
        label, value = " ".join(words[:cut]), " ".join(words[cut:])
        f = _label_field(label)
        if f and value.strip(":# "):
            return f, label, value.strip(":# ")
    return None


def _value_type(text: str) -> HeaderField | None:
    t = text.strip()
    if parse_date(t):
        return "date"
    if re.fullmatch(r"C\d{5,7}|\d{6,7}", t):
        return "number"
    if re.fullmatch(r"\d{3,6}", t) or t in ("—", "-", "Guest"):
        return "customer"
    if re.fullmatch(r"[A-Za-z][A-Za-z .'-]{1,40}", t):
        return "country"
    return None


def _is_label_row(row: Row, below: Row | None) -> bool:
    """A row of labels with their values underneath (labels in boxes): three or more
    cells, none of them a value, each with a cell starting at the same x in the next
    row."""
    if below is None or len(row.segs) < 3:
        return False
    if any(_value_type(s.text) in ("date", "number", "customer") for s in row.segs):
        return False
    aligned = sum(1 for s in row.segs if any(abs(t.x0 - s.x0) < 8 for t in below.segs))
    return aligned >= max(3, len(row.segs) - 1)


def _header_fields(  # noqa: PLR0912 - two layouts, then elimination
    rows: Sequence[Row], notes: list[str]
) -> dict[HeaderField, FieldValue]:
    """Label/value pairs above the table, read as fields. Pairs come in two layouts:
    labels in a row with the values underneath, or label and value side by side. A pair
    whose label is not recognised is used by elimination when its value has the type of a
    field still missing; side-by-side pairs only count if both label and value line up
    with the recognised pairs, so a title or the seller's name is not taken for one."""
    pairs: list[tuple[Seg, Seg, HeaderField | None, bool]] = []  # label, value, field, stacked
    for i, row in enumerate(rows):
        nxt = rows[i + 1] if i + 1 < len(rows) else None
        if _is_label_row(row, nxt):
            assert nxt is not None  # noqa: S101
            for seg in row.segs:
                value = min(
                    (t for t in nxt.segs if abs(t.x0 - seg.x0) < 8),
                    key=lambda t: abs(t.x0 - seg.x0),
                    default=None,
                )
                if value is not None:
                    pairs.append((seg, value, _label_field(seg.text), True))
            continue
        for k, seg in enumerate(row.segs):
            f = _label_field(seg.text)
            if f and k + 1 < len(row.segs) and not _label_field(row.segs[k + 1].text):
                pairs.append((seg, row.segs[k + 1], f, False))
            elif f is None and (inline := _inline(seg)):
                name, label_text, value_text = inline
                label_seg = Seg(seg.page, label_text, seg.x0, seg.top, seg.x0, seg.bottom, seg.bold)
                value_seg = Seg(seg.page, value_text, seg.x0, seg.top, seg.x1, seg.bottom, seg.bold)
                pairs.append((label_seg, value_seg, name, False))
    side = [(lab, val) for lab, val, f, stacked in pairs if f and not stacked]
    if side:
        # Grow the block of side-by-side pairs row by row: a row joins when its label and
        # value line up with the block's and it is within a couple of lines of a member.
        step = 2.2 * max(lab.height for lab, _ in side)
        block_tops = [lab.top for lab, _ in side]
        candidates = [
            r for r in rows
            if len(r.segs) == 2 and not _label_field(r.segs[0].text)
            and not any(r.segs[0] is a for a, _ in side)
            and any(abs(r.segs[0].x0 - a.x0) < 8 for a, _ in side)
            and any(abs(r.segs[1].x0 - v.x0) < 8 for _, v in side)
        ]  # fmt: skip
        grown = True
        while grown:
            grown = False
            for r in list(candidates):
                if any(abs(r.segs[0].top - t) <= step for t in block_tops):
                    pairs.append((r.segs[0], r.segs[1], None, False))
                    block_tops.append(r.segs[0].top)
                    candidates.remove(r)
                    grown = True
    found: dict[HeaderField, FieldValue] = {}
    for lab, val, f, _stacked in pairs:
        if f and f not in found:
            found[f] = FieldValue(val.text, val.text, Box.around([val]), lab.text, "label")
    missing = [f for f in FIELDS if f not in found]
    for lab, val, f, _stacked in pairs:
        if f is not None or not re.search(r"[A-Za-z]{2}", lab.text):
            continue
        kind = _value_type(val.text)
        if kind in missing:
            found[kind] = FieldValue(val.text, val.text, Box.around([val]), lab.text,
                                     "elimination")  # fmt: skip
            missing.remove(kind)
            notes.append(f"“{lab.text}” read as the {kind} field from its value")
    return found


def _finish_fields(found: dict[HeaderField, FieldValue]) -> dict[HeaderField, FieldValue]:
    out: dict[HeaderField, FieldValue] = {}
    for f in FIELDS:
        fv = found.get(f, FieldValue())
        text = (fv.text or "").strip()
        if f == "number":
            fv.value = text.replace(" ", "") or None
        elif f == "date":
            fv.value = parse_date(text) if text else None
        elif f == "customer":
            fv.value = int(text) if re.fullmatch(r"\d+", text) else None
        else:
            fv.value = text or None
        out[f] = fv
    return out


# --------------------------------------------------------------------------- totals
def _totals(rows: Sequence[Row], start: int, cols: Sequence[Column], ex: Extraction) -> None:
    amount_col = next((c for c in cols if c.role == "amount"), None)
    candidates: list[tuple[str, Seg, Row]] = []
    for row in rows[start : start + 6]:
        if _is_footer(row):
            break
        money = [s for s in row.segs if parse_money(s.text) is not None]
        label = _row_label(row)
        if label in _ITEMS:
            ints = [s for s in row.segs if parse_quantity(s.text) is not None]
            if ints:
                ex.item_count = parse_quantity(ints[-1].text)
            continue
        if not money:
            continue
        # The amount under the amount column, or the right-most one.
        seg = min(money, key=lambda s: abs(s.x1 - amount_col.x1)) if amount_col else money[-1]
        candidates.append((label, seg, row))
    total = next(((lab, s, r) for lab, s, r in candidates if lab in _TOTALS), None)
    by: Literal["label", "fallback"] = "label"
    if total is None and candidates:
        total = candidates[-1]
        by = "fallback"
        ex.notes.append(f"Total read from the last amount after the table (“{total[0]}”)")
    for lab, s, _row in candidates:
        if lab == _SUBTOTAL:
            ex.subtotal = FieldValue(parse_money(s.text), s.text, Box.around([s]), lab, "label")
    if total:
        lab, s, r = total
        label_seg = next((t for t in r.segs if t is not s), None)
        ex.total = FieldValue(
            parse_money(s.text), s.text, Box.around([s]),
            label_seg.text if label_seg else None, by,
        )  # fmt: skip


# --------------------------------------------------------------------------- checks
def _checks(ex: Extraction) -> list[Check]:
    checks: list[Check] = []

    def multiplies(ln: ExtractedLine) -> bool:
        if ln.quantity is None or ln.unit_price is None or ln.amount is None:
            return False
        return abs(ln.quantity * ln.unit_price - ln.amount) < Decimal("0.005")

    bad = [i + 1 for i, ln in enumerate(ex.lines) if not multiplies(ln)]
    checks.append(Check(
        "line_arithmetic",
        bool(ex.lines) and not bad,
        "Every line: quantity × unit price = amount"
        if ex.lines and not bad
        else ("No line items found" if not ex.lines
              else f"Lines {', '.join(map(str, bad[:8]))}{'…' if len(bad) > 8 else ''} "
                   "do not multiply out"),
    ))  # fmt: skip
    amounts = [ln.amount for ln in ex.lines if ln.amount is not None]
    total = ex.total.value
    if total is None:
        checks.append(Check("total_matches_lines", False, "No total found"))
    else:
        s = sum(amounts, Decimal(0))
        ok = len(amounts) == len(ex.lines) and abs(s - total) < Decimal("0.005")
        checks.append(Check(
            "total_matches_lines", ok,
            f"Line amounts add up to the total ({total})" if ok
            else f"Line amounts add up to {s}, the total says {total}",
        ))  # fmt: skip
    if ex.item_count is not None:
        ok = ex.item_count == len(ex.lines)
        checks.append(Check("item_count", ok, f"{len(ex.lines)} lines read; the invoice "
                                              f"says {ex.item_count}"))  # fmt: skip
    missing = [f for f in ("number", "date") if ex.fields[f].value is None]
    checks.append(Check(
        "header_complete", not missing,
        "Invoice number and date found" if not missing
        else f"Not found: {', '.join(missing)}",
    ))  # fmt: skip
    if total is not None and ex.document_type is not None:
        ok = (total < 0) == (ex.document_type == "credit_note") or total == 0
        checks.append(Check(
            "sign", ok,
            "Credit note with a negative total" if ex.document_type == "credit_note" and ok
            else "Invoice with a positive total" if ok
            else "The total's sign does not match the document type",
        ))  # fmt: skip
    return checks


# --------------------------------------------------------------------------- entry point
def extract_invoice(pages: Sequence[RawPage]) -> Extraction:
    """Read the invoice on ``pages`` (from ``read_pdf(..., segments=True)``)."""
    ex = Extraction()
    rows = rows_of(pages)
    if not rows:
        ex.notes.append("No text was found")
        ex.fields = _finish_fields({})
        ex.checks = _checks(ex)
        return ex
    head = _find_header(rows)
    first_page = rows[0].page
    region = [r for r in rows[: head if head is not None else len(rows)] if r.page == first_page]
    ex.fields = _finish_fields(_header_fields(region, ex.notes))
    text = " ".join(r.text.lower() for r in region)
    ex.document_type = "credit_note" if "credit note" in text else "invoice"
    if head is None:
        ex.notes.append("No item table was recognised")
        ex.checks = _checks(ex)
        return ex
    cols = _columns(rows[head])
    body = _body(rows, head)
    bands = _bands(cols, body)
    sample = [[cell_text(c) for c in _cells(r, bands)] for r in body if _looks_like_item(r)]
    _assign_by_content(cols, sample, ex.notes)
    items, end = _read_table(rows, head, cols, bands)
    table = [[cell_text(c) for c in item] for item in items]
    ex.columns = cols
    for item, cells_text in zip(items, table, strict=True):
        cells: dict[Role, str] = {}
        for c, t in zip(cols, cells_text, strict=True):
            if c.role and t:
                cells[c.role] = t
        segs = [s for c in item for s in c]
        line = ExtractedLine(cells=cells, box=Box.around(segs))
        line.stock_code = cells.get("code") or None
        line.description = " ".join(cells.get("description", "").split()) or None
        line.quantity = parse_quantity(cells.get("quantity", ""))
        line.unit_price = parse_money(cells.get("unit_price", ""))
        line.amount = parse_money(cells.get("amount", ""))
        ex.lines.append(line)
    _totals(rows, end, cols, ex)
    if ex.fields["number"].value and str(ex.fields["number"].value).startswith("C"):
        ex.document_type = "credit_note"
    ex.checks = _checks(ex)
    return ex


def summary(ex: Extraction) -> dict[str, Any]:
    """The extracted values only, as plain JSON (what a downstream system would store)."""
    return {
        "document_type": ex.document_type,
        "number": ex.fields["number"].value,
        "date": ex.fields["date"].value.date().isoformat() if ex.fields["date"].value else None,
        "customer_id": ex.fields["customer"].value,
        "country": ex.fields["country"].value,
        "total": None if ex.total.value is None else str(ex.total.value),
        "lines": [
            {k: v for k, v in ln.to_json().items() if k not in ("cells", "box")} for ln in ex.lines
        ],
    }


def iter_boxes(ex: Extraction) -> Iterable[tuple[str, Box]]:
    """Where each value was read from, for drawing on the page preview."""
    for name, fv in ex.fields.items():
        if fv.box:
            yield name, fv.box
    if ex.total.box:
        yield "total", ex.total.box
    for i, ln in enumerate(ex.lines):
        if ln.box:
            yield f"line-{i + 1}", ln.box
