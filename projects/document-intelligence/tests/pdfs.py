"""Small PDFs built with reportlab for the tests: text pages, headings, a scanned page."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    ListFlowable,
    ListItem,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
)

FONT_DIR = Path("/usr/share/fonts/truetype/dejavu")

POLICY = [
    ("title", "Returns and Refunds Handbook"),
    ("h1", "1 Scope"),
    (
        "p",
        "This handbook explains how customers of the shop can return goods and how refunds "
        "are calculated. It applies to orders delivered in the United Kingdom and in the "
        "European Union. Staff should read it before answering any refund question.",
    ),
    ("h2", "1.1 Who may ask for a refund"),
    (
        "p",
        "Any customer with an account may ask for a refund within thirty days of delivery. "
        "Guests who ordered without an account must give the invoice number instead.",
    ),
    ("h1", "2 Damaged items"),
    (
        "p",
        "If an item arrives damaged, the customer receives a full refund including the "
        "original delivery charge, provided the damage is reported within fourteen days. "
        "Photographs help but are not required. A replacement can be sent instead of a "
        "refund when the item is still in stock.",
    ),
    (
        "bullets",
        [
            "Report the damage within fourteen days.",
            "Keep the packaging until the claim is closed.",
            "Refunds are paid to the original payment method.",
        ],
    ),
    ("break", ""),
    ("h1", "3 Lost parcels"),
    (
        "p",
        "A parcel counts as lost when tracking shows no movement for ten working days. The "
        "warehouse then opens an investigation with the carrier. Customers are refunded in "
        "full once the investigation confirms the loss, which usually takes five working "
        "days. Parcels sent by the economy service are investigated only after fifteen "
        "working days because that service has no tracking.",
    ),
    ("h2", "3.1 Supervisor approval"),
    (
        "p",
        "Refunds above fifty pounds need the approval of a supervisor before they are paid. "
        "The supervisor checks the order history and the carrier's response, and records the "
        "decision on the ticket so that the customer can be told the outcome.",
    ),
]


def _styles() -> dict[str, ParagraphStyle]:
    ss = getSampleStyleSheet()
    return {"title": ss["Title"], "h1": ss["Heading1"], "h2": ss["Heading2"], "p": ss["BodyText"]}


def _header_footer(canvas: Canvas, doc: SimpleDocTemplate) -> None:
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.drawString(72, A4[1] - 40, "Example Shop Ltd - internal handbook v2")
    canvas.drawRightString(A4[0] - 72, 30, f"Page {doc.page}")
    canvas.restoreState()


def policy_pdf(extra_pages: int = 0) -> bytes:
    styles = _styles()
    story: list[object] = []
    for kind, text in POLICY:
        if kind == "break":
            story.append(PageBreak())
        elif kind == "bullets":
            story.append(
                ListFlowable(
                    [ListItem(Paragraph(t, styles["p"])) for t in text],  # type: ignore[union-attr]
                    bulletType="bullet",
                )
            )
        else:
            story.append(Paragraph(str(text), styles[kind]))
            story.append(Spacer(1, 4))
    for i in range(extra_pages):
        story.append(PageBreak())
        story.append(Paragraph(f"Appendix {i + 1}", styles["h1"]))
        story.append(Paragraph("Notes on regional carriers and delivery times. " * 20, styles["p"]))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, title="Returns handbook").build(
        story, onFirstPage=_header_footer, onLaterPages=_header_footer
    )
    return buf.getvalue()


def text_image(lines: list[str], *, width: int = 1240, height: int = 1754) -> Image.Image:
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)
    big = ImageFont.truetype(str(FONT_DIR / "DejaVuSans-Bold.ttf"), 44)
    body = ImageFont.truetype(str(FONT_DIR / "DejaVuSans.ttf"), 28)
    y = 120
    for i, line in enumerate(lines):
        font = big if i == 0 else body
        draw.text((110, y), line, font=font, fill="black")
        y += 90 if i == 0 else 46
    return img


def scanned_pdf(pages: list[list[str]]) -> bytes:
    """A PDF whose pages are only images of text, like a scan."""
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=A4)
    for lines in pages:
        img = text_image(lines)
        c.drawImage(ImageReader(img), 0, 0, width=A4[0], height=A4[1])
        c.showPage()
    c.save()
    return buf.getvalue()


SCAN_PAGE = [
    "Delivery charges",
    "Standard delivery within the UK costs four pounds.",
    "Orders over fifty pounds are delivered free of charge.",
    "Next day delivery costs nine pounds and must be ordered by 2 pm.",
]
