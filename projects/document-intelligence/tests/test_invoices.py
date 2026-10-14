"""Invoice extraction: parsing, the extractor on rendered invoices, checks and scoring.

The invoices here are written in the test (not drawn from the retail data), rendered in
dev and held-out layouts, read back and compared value by value.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from reluai_docs.invoices.evaluate import compare, field_report, summarise
from reluai_docs.invoices.extract import (
    extract_invoice,
    parse_date,
    parse_money,
    parse_quantity,
)
from reluai_docs.invoices.records import (
    EvalDocument,
    InvoiceLine,
    InvoiceRecord,
    evaluation_set,
    load_set,
    select_invoices,
    write_set,
)
from reluai_docs.invoices.render import FOOTER, document_pdf, render_invoice, style_for
from reluai_docs.pdfread import ReadLimits, read_pdf

LINES = (
    InvoiceLine("85123A", "WHITE HANGING HEART T-LIGHT HOLDER", 6, Decimal("2.55")),
    InvoiceLine("22752", "SET 7 BABUSHKA NESTING BOXES", 2, Decimal("7.65")),
    InvoiceLine("POST", "POSTAGE", 1, Decimal("18.00")),
    InvoiceLine("21730", "GLASS STAR FROSTED T-LIGHT HOLDER", 48, Decimal("3.75")),
)
INVOICE = InvoiceRecord("536365", datetime(2010, 12, 1, 8, 26), 17850, "United Kingdom", LINES)
CREDIT = InvoiceRecord(
    "C536379",
    datetime(2010, 12, 1, 9, 41),
    None,
    "EIRE",
    (InvoiceLine("22556", "PLASTERS IN TIN CIRCUS PARADE", -12, Decimal("1.65")),),
)


def _read(pdf: bytes) -> list:  # type: ignore[type-arg]
    return read_pdf(pdf, ReadLimits(segments=True)).pages


# --------------------------------------------------------------------------- parsing
@pytest.mark.parametrize(
    ("text", "value"),
    [("2.55", "2.55"), ("£1,234.50", "1234.50"), ("(12.50)", "-12.50"), ("-£3.90", "-3.90"),
     ("GBP 7.65", "7.65"), ("−0.42", "-0.42"), ("1.5", None), ("12", None), ("£", None)],
)  # fmt: skip
def test_parse_money(text: str, value: str | None) -> None:
    assert parse_money(text) == (Decimal(value) if value else None)


def test_parse_quantity_and_date() -> None:
    assert parse_quantity("(7)") == -7
    assert parse_quantity("1,200") == 1200
    assert parse_quantity("2.5") is None
    assert parse_date("1 December 2010 08:26") == datetime(2010, 12, 1, 8, 26)
    assert parse_date("2010-12-01") == datetime(2010, 12, 1)
    assert parse_date("01.12.2010") == datetime(2010, 12, 1)
    assert parse_date("not a date") is None


# --------------------------------------------------------------------------- round trips
@pytest.mark.parametrize("seed", [1, 4, 6, 10, 11, 1001, 1004, 1007, 1012])
def test_rendered_invoice_is_read_exactly(seed: int) -> None:
    for record in (INVOICE, CREDIT):
        ex = extract_invoice(_read(render_invoice(record, style_for(seed))))
        c = compare(ex, record)
        assert c.exact, (seed, record.number, c.mismatches)
        assert not ex.needs_review


def test_long_invoice_runs_over_pages() -> None:
    lines = tuple(
        InvoiceLine(f"2{i:04d}", f"ITEM NUMBER {i} IN A LONG ORDER", i % 7 + 1, Decimal("1.25"))
        for i in range(58)
    )
    record = dataclasses.replace(INVOICE, lines=lines)
    pdf = render_invoice(record, style_for(3))
    pages = _read(pdf)
    assert len(pages) >= 2
    ex = extract_invoice(pages)
    assert compare(ex, record).exact
    assert ex.total.value == record.total


def test_unfamiliar_wording_is_resolved_from_content() -> None:
    style = dataclasses.replace(
        style_for(2),
        headers={"code": "Zeta", "description": "Narrative", "quantity": "Count",
                 "unit_price": "Tariff", "amount": "Extended"},
        labels={"number": "Serial", "date": "When", "customer": "Payer", "country": "Land"},
        total_label="Grand sum",
    )  # fmt: skip
    ex = extract_invoice(_read(render_invoice(INVOICE, style)))
    assert compare(ex, INVOICE).exact
    assert {c.role for c in ex.columns if c.by == "content"} == {
        "code", "description", "quantity", "unit_price", "amount"
    }  # fmt: skip
    assert any("read as" in n for n in ex.notes)


def test_checks_flag_wrong_values() -> None:
    from reluai_docs.invoices.extract import _checks

    ex = extract_invoice(_read(render_invoice(INVOICE, style_for(1))))
    ex.lines[1].amount = Decimal("15.00")  # as if 15.30 had been misread
    checks = {c.name: c for c in _checks(ex)}
    assert not checks["line_arithmetic"].passed and "2" in checks["line_arithmetic"].detail
    assert not checks["total_matches_lines"].passed


def test_not_an_invoice() -> None:
    from .pdfs import policy_pdf

    ex = extract_invoice(_read(policy_pdf()))
    assert ex.needs_review
    assert not ex.lines


def test_every_page_says_it_is_a_rendering() -> None:
    pdf = render_invoice(INVOICE, style_for(5))
    text = " ".join(ln.text for p in read_pdf(pdf, ReadLimits()).pages for ln in p.lines)
    assert FOOTER.split(":")[0] in text


# --------------------------------------------------------------------------- scoring
def test_compare_pairs_lines_and_reports() -> None:
    from reluai_docs.invoices.extract import _checks

    ex = extract_invoice(_read(render_invoice(INVOICE, style_for(1))))
    del ex.lines[2]  # a line the extractor missed
    ex.checks = _checks(ex)
    c = compare(ex, INVOICE)
    assert not c.exact and c.paired == 3 and c.truth_lines == 4
    report = field_report(ex, INVOICE)
    assert report["missing"][0]["stock_code"] == "POST"
    assert report["header"]["total"]["correct"]
    s = summarise([c])
    assert s["exact"] == 0 and s["line_recall"] == 75.0
    assert s["silently_wrong"] == 0  # the total no longer adds up, so it was flagged


# --------------------------------------------------------------------------- the set
def test_selection_rules_and_split(tmp_path: Path) -> None:
    cols = ["invoice", "stock_code", "description", "quantity", "invoice_date", "price",
            "customer_id", "country"]  # fmt: skip
    rows = [
        (f"{500000 + n}", f"{20000 + k}", f"PRODUCT {k}", 2, datetime(2011, 1, 1), 1.25,
         12000.0 + n, "United Kingdom")
        for n in range(300)
        for k in range(1 + n % 35)
    ]  # fmt: skip
    for n in range(12):  # credit notes and invoices without a customer
        rows.append((f"C{560000 + n}", "22000", "RETURNED THING", -1, datetime(2011, 2, 1),
                     2.0, 13000.0, "France"))  # fmt: skip
        rows.append((f"{570000 + n}", "22001", "GUEST ORDER", 3, datetime(2011, 3, 1),
                     1.0, None, "Germany"))  # fmt: skip
    rows += [  # excluded: an administrative line, a price in fractions of a penny
        ("580000", "B", "Adjust bad debt", 1, datetime(2011, 4, 1), 10.0, None, "United Kingdom"),
        ("580001", "22002", "ODD PRICE", 1, datetime(2011, 4, 1), 0.125, 1.0, "United Kingdom"),
    ]
    df = pd.DataFrame(rows, columns=cols)
    df["invoice"] = df["invoice"].astype("string")
    df["stock_code"] = df["stock_code"].astype("string")
    df["customer_id"] = df["customer_id"].astype("Int64")
    path = tmp_path / "retail.parquet"
    df.to_parquet(path)
    chosen = select_invoices(path)
    numbers = {split: {r.number for r in recs} for split, recs in chosen.items()}
    assert not numbers["dev"] & numbers["held_out"]
    every = numbers["dev"] | numbers["held_out"]
    assert "580000" not in every and "580001" not in every
    assert sum(r.credit_note for r in chosen["dev"]) == 4
    assert sum(r.customer_id is None for r in chosen["held_out"]) == 4
    assert chosen == select_invoices(path)  # reproducible
    docs = evaluation_set(chosen)
    write_set(docs, tmp_path / "invoices.json")
    again = load_set(tmp_path / "invoices.json")
    assert again == docs
    assert {d.style >= 1000 for d in docs if d.split == "held_out"} == {True}


def test_simulated_scan_is_the_same_bytes_every_time(monkeypatch: pytest.MonkeyPatch) -> None:
    import time

    from PIL import PdfImagePlugin

    from reluai_docs.invoices.scan import simulate_scan

    pdf = render_invoice(CREDIT, style_for(2))
    first = simulate_scan(pdf, seed=7, dpi=60)
    later = time.gmtime(time.time() + 3600)
    monkeypatch.setattr(PdfImagePlugin.time, "gmtime", lambda *_: later)  # an hour on
    assert simulate_scan(pdf, seed=7, dpi=60) == first
    assert simulate_scan(pdf, seed=8, dpi=60) != first


@pytest.mark.slow
def test_simulated_scan_is_read_with_ocr() -> None:
    doc = EvalDocument("536365-s4-scan", "dev", INVOICE, 4, True)
    pdf = document_pdf(doc)
    assert document_pdf(doc) == pdf  # the same scan every time
    pages = read_pdf(pdf, ReadLimits(segments=True)).pages
    assert pages[0].method == "ocr"
    ex = extract_invoice(pages)
    c = compare(ex, INVOICE)
    assert c.header["number"] and c.header["total"], c.mismatches
    assert c.paired == 4
