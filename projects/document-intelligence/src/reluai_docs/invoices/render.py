"""Draw a real invoice record as a PDF, in a layout generated from a seed.

Real invoices from different suppliers differ in everything an extractor relies on: where
the header fields sit and what they are called, the order and names of the table columns,
date and number formats, fonts and rules, and where pages break. ``style_for(seed)`` draws
one combination of those choices, so the evaluation can be run on layouts the extractor
was developed on (dev seeds) and on combinations it has never seen (held-out seeds).

Some wordings are reserved for held-out seeds (``_HELD_OUT_*``): the extractor's own
vocabulary was written from the dev wordings only, so the held-out set also measures what
happens when a label or column header is unfamiliar.

Every page carries a footer saying the document is a rendering of public dataset records,
not a real invoice. The retailer is not named (the dataset does not name it).
"""

from __future__ import annotations

import io
import random
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from reportlab.lib.pagesizes import A4, LETTER
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from reluai_docs.invoices.records import EvalDocument, InvoiceLine, InvoiceRecord

Column = Literal["code", "description", "quantity", "unit_price", "amount"]
FieldName = Literal["number", "date", "customer", "country"]

FOOTER = (
    "Portfolio demonstration: rendered from public dataset records (UCI Online Retail II, "
    "CC BY 4.0). Not a real invoice."
)
SELLER = ("UK online gift retailer", "Name not published in the source dataset")

# Wordings used for dev seeds; the extractor's vocabulary is written from these.
_DEV_LABELS: dict[FieldName, tuple[str, ...]] = {
    "number": ("{doc} no.", "{doc} number", "{doc} #", "Number"),
    "date": ("Date", "{doc} date", "Issued", "Date of issue"),
    "customer": ("Customer", "Customer ID", "Customer no.", "Account"),
    "country": ("Country", "Ship to", "Delivery country"),
}
_DEV_HEADERS: dict[Column, tuple[str, ...]] = {
    "code": ("Code", "Stock code", "Item", "SKU"),
    "description": ("Description", "Item description", "Product"),
    "quantity": ("Qty", "Quantity", "Units"),
    "unit_price": ("Unit price", "Price", "Unit cost"),
    "amount": ("Amount", "Total", "Line total"),
}
_DEV_TOTALS = ("Total", "Total due", "Amount due", "Invoice total")
# Wordings that only held-out seeds may use.
_HELD_OUT_LABELS: dict[FieldName, tuple[str, ...]] = {
    "number": ("Document ref.", "Ref"),
    "date": ("Dated", "Document date"),
    "customer": ("Client", "Buyer ref."),
    "country": ("Destination", "Deliver to"),
}
_HELD_OUT_HEADERS: dict[Column, tuple[str, ...]] = {
    "code": ("Article", "Ref."),
    "description": ("Details", "Goods"),
    "quantity": ("Pcs", "No. of units"),
    "unit_price": ("Each", "Rate"),
    "amount": ("Net", "Value"),
}
_HELD_OUT_TOTALS = ("Balance due", "Sum payable")

_ORDERS: tuple[tuple[Column, ...], ...] = (
    ("code", "description", "quantity", "unit_price", "amount"),
    ("description", "code", "quantity", "unit_price", "amount"),
    ("code", "description", "unit_price", "quantity", "amount"),
    ("quantity", "code", "description", "unit_price", "amount"),
    ("code", "quantity", "description", "unit_price", "amount"),
)
_DATE_FORMATS = ("%d/%m/%Y", "%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%d.%m.%Y", "%d-%b-%Y")
_FONTS = (
    ("Helvetica", "Helvetica-Bold"),
    ("Times-Roman", "Times-Bold"),
    ("Courier", "Courier-Bold"),
)
_WIDTH: dict[Column, float] = {"code": 58, "quantity": 42, "unit_price": 62, "amount": 68}


@dataclass(frozen=True, slots=True)
class Style:
    seed: int
    page: tuple[float, float]
    font: str
    bold: str
    size: float
    title: str
    credit_title: str
    seller_right: bool
    meta: Literal["pairs", "boxes"]
    labels: dict[FieldName, str]
    date_format: str
    show_time: bool
    columns: tuple[Column, ...]
    headers: dict[Column, str]
    upper_headers: bool
    currency: Literal["cells", "header", "none"]
    thousands: bool
    negative: Literal["minus", "parens"]
    rules: Literal["grid", "header", "zebra", "none"]
    total_label: str
    subtotal: bool
    item_count: bool
    missing_customer: Literal["dash", "omit", "guest"]
    margin: float
    row_height: float
    description_width: float | None  # narrower than the space available: descriptions wrap
    rows_per_page: int = field(default=0)  # 0: as many as fit


def _choice(rng: random.Random, dev: Sequence[str], held: Sequence[str], held_out: bool) -> str:
    """A wording: from the dev list, or for held-out seeds sometimes a reserved one."""
    if held_out and held and rng.random() < 0.4:
        return rng.choice(list(held))
    return rng.choice(list(dev))


def style_for(seed: int) -> Style:
    """The layout for ``seed``; seeds of 1000 and above are held-out layouts."""
    rng = random.Random(seed * 7919 + 13)  # noqa: S311 - reproducible choices, not security
    held = seed >= 1000
    font, bold = rng.choice(_FONTS)
    size = rng.choice((8.0, 8.5, 9.0, 9.5)) if font != "Courier" else rng.choice((7.5, 8.0, 8.5))
    labels = {k: _choice(rng, _DEV_LABELS[k], _HELD_OUT_LABELS[k], held) for k in _DEV_LABELS}
    headers = {k: _choice(rng, _DEV_HEADERS[k], _HELD_OUT_HEADERS[k], held) for k in _DEV_HEADERS}
    title = rng.choice(("INVOICE", "Invoice", "Sales invoice"))
    return Style(
        seed=seed,
        page=rng.choice((A4, A4, LETTER)),
        font=font,
        bold=bold,
        size=size,
        title=title,
        credit_title="CREDIT NOTE" if title.isupper() else "Credit note",
        seller_right=rng.random() < 0.4,
        meta=rng.choice(("pairs", "pairs", "boxes")),
        labels=labels,
        date_format=rng.choice(_DATE_FORMATS),
        show_time=rng.random() < 0.3,
        columns=rng.choice(_ORDERS),
        headers=headers,
        upper_headers=rng.random() < 0.3,
        currency=rng.choice(("cells", "header", "none")),
        thousands=rng.random() < 0.6,
        negative=rng.choice(("minus", "minus", "parens")),
        rules=rng.choice(("grid", "header", "zebra", "none")),
        total_label=_choice(rng, _DEV_TOTALS, _HELD_OUT_TOTALS, held),
        subtotal=rng.random() < 0.4,
        item_count=rng.random() < 0.25,
        missing_customer=rng.choice(("dash", "omit", "guest")),
        margin=rng.choice((40.0, 48.0, 56.0)),
        row_height=round(size * rng.choice((1.5, 1.7, 1.9)), 1),
        description_width=rng.choice((None, None, 150.0)),
    )


# --------------------------------------------------------------------------- formatting
def _money(value: Decimal, style: Style, *, cell: bool) -> str:
    text = f"{abs(value):,.2f}" if style.thousands else f"{abs(value):.2f}"
    if style.currency == "cells" or (not cell and style.currency != "none"):
        text = f"£{text}"
    if value < 0:
        text = f"({text})" if style.negative == "parens" else f"-{text}"
    return text


def _quantity(value: int, style: Style) -> str:
    if value < 0 and style.negative == "parens":
        return f"({abs(value)})"
    return str(value)


def _header(col: Column, style: Style) -> str:
    text = style.headers[col]
    if style.currency == "header" and col in ("unit_price", "amount"):
        text = f"{text} (GBP)"
    return text.upper() if style.upper_headers else text


def _label(name: FieldName, style: Style, inv: InvoiceRecord) -> str:
    doc = "Credit note" if inv.credit_note else "Invoice"
    return style.labels[name].format(doc=doc)


def header_values(inv: InvoiceRecord, style: Style) -> list[tuple[FieldName, str, str]]:
    """The header fields as printed: (field, label, value); a missing customer may be
    left out entirely, depending on the style."""
    date = inv.issued.strftime(style.date_format)
    if style.show_time:
        date += inv.issued.strftime(" %H:%M")
    out: list[tuple[FieldName, str, str]] = [
        ("number", _label("number", style, inv), inv.number),
        ("date", _label("date", style, inv), date),
    ]
    if inv.customer_id is not None:
        out.append(("customer", _label("customer", style, inv), str(inv.customer_id)))
    elif style.missing_customer != "omit":
        value = "—" if style.missing_customer == "dash" else "Guest"
        out.append(("customer", _label("customer", style, inv), value))
    out.append(("country", _label("country", style, inv), inv.country))
    return out


def _wrap(text: str, font: str, size: float, width: float) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if cur and stringWidth(trial, font, size) > width:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    return [*lines, cur] if cur else lines or [""]


# --------------------------------------------------------------------------- drawing
@dataclass(slots=True)
class _Table:
    x: dict[Column, tuple[float, float]]  # left, right of each column
    desc_width: float


def _table_geometry(style: Style) -> _Table:
    page_w = style.page[0]
    left, right = style.margin, page_w - style.margin
    widths = {
        c: max(_WIDTH[c], stringWidth(_header(c, style), style.bold, style.size) + 14)
        for c in style.columns
        if c != "description"
    }
    desc = right - left - sum(widths.values())
    x: dict[Column, tuple[float, float]] = {}
    cur = left
    for c in style.columns:
        w = desc if c == "description" else widths[c]
        x[c] = (cur, cur + w)
        cur += w
    desc_text = min(desc - 8, style.description_width or desc)
    return _Table(x, desc_text)


def _cell(c: Canvas, col: Column, text: str, table: _Table, y: float, style: Style) -> None:  # noqa: PLR0917
    lo, hi = table.x[col]
    if col in ("quantity", "unit_price", "amount"):
        c.drawRightString(hi - 6, y, text)
    else:
        c.drawString(lo + 6, y, text)


def _row_cells(line: InvoiceLine, style: Style) -> dict[Column, str]:
    return {
        "code": line.stock_code,
        "description": line.description,
        "quantity": _quantity(line.quantity, style),
        "unit_price": _money(line.unit_price, style, cell=True),
        "amount": _money(line.amount, style, cell=True),
    }


def _draw_header_row(c: Canvas, table: _Table, y: float, style: Style) -> float:
    left = table.x[style.columns[0]][0]
    right = table.x[style.columns[-1]][1]
    h = style.row_height
    if style.rules in ("grid", "zebra"):
        c.setFillGray(0.88)
        c.rect(left, y - h * 0.3, right - left, h, stroke=0, fill=1)
        c.setFillGray(0)
    c.setFont(style.bold, style.size)
    for col in style.columns:
        _cell(c, col, _header(col, style), table, y, style)
    if style.rules != "none":
        c.setLineWidth(0.6)
        c.line(left, y - h * 0.35, right, y - h * 0.35)
    c.setFont(style.font, style.size)
    return y - h


def _draw_meta(c: Canvas, inv: InvoiceRecord, style: Style, top: float) -> float:
    """Seller, title and header fields; returns the y where the table may start."""
    w, _ = style.page
    m = style.margin
    s = style.size
    title = style.credit_title if inv.credit_note else style.title
    seller_x = w - m if style.seller_right else m
    draw = c.drawRightString if style.seller_right else c.drawString
    c.setFont(style.bold, s + 1)
    draw(seller_x, top, SELLER[0])
    c.setFont(style.font, s - 0.5)
    draw(seller_x, top - s * 1.4, SELLER[1])
    title_x = m if style.seller_right else w - m
    c.setFont(style.bold, s + 9)
    (c.drawString if style.seller_right else c.drawRightString)(title_x, top - 4, title)
    fields = header_values(inv, style)
    y = top - s * 5.5
    if style.meta == "pairs":
        lx = m if style.seller_right else w - m - 210
        for _name, label, value in fields:
            c.setFont(style.bold, s)
            c.drawString(lx, y, f"{label}:" if style.seed % 2 else label)
            c.setFont(style.font, s)
            c.drawString(lx + 95, y, value)
            y -= s * 1.6
    else:  # boxes: labels above values, side by side
        bw = (w - 2 * m) / len(fields)
        for i, (_name, label, value) in enumerate(fields):
            x = m + i * bw
            c.setLineWidth(0.5)
            c.rect(x, y - s * 1.9, bw - 6, s * 3.6, stroke=1, fill=0)
            c.setFont(style.font, s - 1)
            c.drawString(x + 4, y + s * 0.6, label.upper() if style.upper_headers else label)
            c.setFont(style.bold, s)
            c.drawString(x + 4, y - s * 0.9, value)
        y -= s * 4.2
    return y - s * 1.5


def _paginate(inv: InvoiceRecord, style: Style, table: _Table, first_room: float,
              room: float) -> list[list[tuple[InvoiceLine, list[str]]]]:  # fmt: skip
    """Rows (with their wrapped description lines) per page."""
    pages: list[list[tuple[InvoiceLine, list[str]]]] = [[]]
    left = first_room
    for line in inv.lines:
        wrapped = _wrap(line.description, style.font, style.size, table.desc_width)
        need = style.row_height + (len(wrapped) - 1) * style.size * 1.15
        if need > left and pages[-1]:
            pages.append([])
            left = room
        pages[-1].append((line, wrapped))
        left -= need
    return pages


def render_invoice(inv: InvoiceRecord, style: Style) -> bytes:
    """The PDF for ``inv`` drawn in ``style`` (deterministic bytes)."""
    buf = io.BytesIO()
    w, h = style.page
    c = Canvas(buf, pagesize=style.page, invariant=1, pageCompression=1)
    c.setTitle(f"{'Credit note' if inv.credit_note else 'Invoice'} {inv.number}")
    c.setAuthor("reluai.cloud portfolio demonstration")
    table = _table_geometry(style)
    m = style.margin
    bottom = m + 30  # footer
    totals_room = style.row_height * (3 + style.subtotal + style.item_count)
    meta_end = h - m - style.size * 5.5 - (style.size * 1.6 * 4 + style.size * 1.5)
    first_room = meta_end - style.row_height * 1.2 - bottom - totals_room
    room = h - m - style.row_height * 2 - bottom - totals_room
    pages = _paginate(inv, style, table, first_room, room)
    left = table.x[style.columns[0]][0]
    right = table.x[style.columns[-1]][1]
    for p, rows in enumerate(pages, start=1):
        if p == 1:
            y = _draw_meta(c, inv, style, h - m)
        else:
            c.setFont(style.font, style.size)
            c.drawString(m, h - m, f"{inv.number} (continued)")
            y = h - m - style.row_height * 1.5
        y = _draw_header_row(c, table, y, style)
        for i, (line, wrapped) in enumerate(rows):
            cells = _row_cells(line, style)
            extra = (len(wrapped) - 1) * style.size * 1.15
            if style.rules == "zebra" and i % 2:
                c.setFillGray(0.95)
                c.rect(left, y - style.row_height * 0.3 - extra, right - left,
                       style.row_height + extra, stroke=0, fill=1)  # fmt: skip
                c.setFillGray(0)
            for col in style.columns:
                if col == "description":
                    for k, part in enumerate(wrapped):
                        _cell(c, col, part, table, y - k * style.size * 1.15, style)
                else:
                    _cell(c, col, cells[col], table, y, style)
            if style.rules == "grid":
                c.setLineWidth(0.3)
                c.line(left, y - style.row_height * 0.35 - extra, right,
                       y - style.row_height * 0.35 - extra)  # fmt: skip
            y -= style.row_height + extra
        if p == len(pages):
            _draw_totals(c, inv, style, table, y - style.row_height * 0.4)
        c.setFont(style.font, style.size - 1.5)
        c.drawString(m, m, FOOTER)
        c.drawRightString(w - m, m + style.size * 1.4, f"Page {p} of {len(pages)}")
        c.showPage()
    c.save()
    return buf.getvalue()


def _draw_totals(c: Canvas, inv: InvoiceRecord, style: Style, table: _Table, y: float) -> None:
    lo, hi = table.x["amount"]
    label_x = min(lo, table.x["unit_price"][0]) - 90
    rows: list[tuple[str, str]] = []
    if style.item_count:
        rows.append(("Items", str(len(inv.lines))))
    total = _money(inv.total, style, cell=False)
    if style.subtotal:
        rows.append(("Subtotal", total))
    rows.append((style.total_label, total))
    c.setLineWidth(0.6)
    c.line(label_x, y + style.row_height * 0.6, hi, y + style.row_height * 0.6)
    for i, (label, value) in enumerate(rows):
        last = i == len(rows) - 1
        c.setFont(style.bold if last else style.font, style.size + (1 if last else 0))
        c.drawString(label_x, y, label.upper() if style.upper_headers else label)
        c.drawRightString(hi - 6, y, value)
        y -= style.row_height


def document_pdf(doc: EvalDocument) -> bytes:
    """The PDF of an evaluation document: the invoice in its layout, scanned if it is a
    scan (the same "scan" every time: the seed comes from the document's id)."""
    from reluai_docs.invoices.scan import simulate_scan

    pdf = render_invoice(doc.invoice, style_for(doc.style))
    return simulate_scan(pdf, seed=zlib.crc32(doc.id.encode())) if doc.scanned else pdf
