"""Compare an extraction with the record it was rendered from, field by field.

Header fields (number, date, customer, country), the document type and the total are
right or wrong. Line items are paired with the record's lines in order (a line read with
a wrong stock code still pairs with its neighbour-consistent counterpart), then each of
the five values is compared. A document is **exact** when every field and every line is
right and no line is missing or extra.

The checks are judged too: the useful outcome is that a wrong extraction is flagged for
review (caught) and a right one is not (no false alarm). "Silently wrong" (wrong, but
every check passed) is the number that matters most for automation.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from reluai_docs.invoices.extract import ExtractedLine, Extraction
from reluai_docs.invoices.records import EvalDocument, InvoiceLine, InvoiceRecord
from reluai_docs.pdfread import ReadResult

LINE_FIELDS = ("stock_code", "description", "quantity", "unit_price", "amount")
HEADER = ("number", "date", "customer", "country", "document_type", "total")


@dataclass(slots=True)
class Comparison:
    header: dict[str, bool]
    truth_lines: int
    read_lines: int
    paired: int
    line_fields: dict[str, int]  # correct values per field, over paired lines
    lines_exact: int  # paired lines with all five values right
    needs_review: bool
    mismatches: list[str] = field(default_factory=list)

    @property
    def exact(self) -> bool:
        return (
            all(self.header.values())
            and self.paired == self.truth_lines == self.read_lines == self.lines_exact
        )

    def to_json(self) -> dict[str, Any]:
        return {
            "header": self.header,
            "truth_lines": self.truth_lines,
            "read_lines": self.read_lines,
            "paired": self.paired,
            "line_fields": self.line_fields,
            "lines_exact": self.lines_exact,
            "exact": self.exact,
            "needs_review": self.needs_review,
            "mismatches": self.mismatches[:12],
        }


def _same(read: ExtractedLine, truth: InvoiceLine) -> dict[str, bool]:
    return {
        "stock_code": read.stock_code == truth.stock_code,
        "description": (read.description or "") == " ".join(truth.description.split()),
        "quantity": read.quantity == truth.quantity,
        "unit_price": read.unit_price == truth.unit_price,
        "amount": read.amount == truth.amount,
    }


def _pairs(read: list[ExtractedLine], truth: tuple[InvoiceLine, ...]) -> list[tuple[int, int]]:
    """Pair read lines with record lines, in order: equal stock codes first, then the
    lines between two anchors position by position."""
    a = [ln.stock_code or "?" for ln in read]
    b = [ln.stock_code for ln in truth]
    pairs: list[tuple[int, int]] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if tag in {"equal", "replace"}:
            pairs += list(zip(range(i1, i2), range(j1, j2), strict=False))
    return pairs


def compare(ex: Extraction, truth: InvoiceRecord) -> Comparison:
    f = ex.fields
    date = f["date"].value
    header = {
        "number": f["number"].value == truth.number,
        "date": date is not None and date.date() == truth.issued.date(),
        "customer": f["customer"].value == truth.customer_id,
        "country": f["country"].value == truth.country,
        "document_type": (ex.document_type == "credit_note") == truth.credit_note,
        "total": ex.total.value == truth.total,
    }
    mismatches = [
        f"{name}: read {_shown(ex, name)!r}, record {_truth(truth, name)!r}"
        for name, ok in header.items()
        if not ok
    ]
    pairs = _pairs(ex.lines, truth.lines)
    counts = dict.fromkeys(LINE_FIELDS, 0)
    exact_lines = 0
    for i, j in pairs:
        same = _same(ex.lines[i], truth.lines[j])
        for k, ok in same.items():
            counts[k] += ok
        exact_lines += all(same.values())
        for k, ok in same.items():
            if not ok:
                mismatches.append(
                    f"line {j + 1} {k}: read {getattr(ex.lines[i], k)!r}, "
                    f"record {getattr(truth.lines[j], k)!r}"
                )
    if len(ex.lines) != len(truth.lines):
        mismatches.append(f"{len(ex.lines)} lines read, the record has {len(truth.lines)}")
    return Comparison(
        header=header,
        truth_lines=len(truth.lines),
        read_lines=len(ex.lines),
        paired=len(pairs),
        line_fields=counts,
        lines_exact=exact_lines,
        needs_review=ex.needs_review,
        mismatches=mismatches,
    )


def _shown(ex: Extraction, name: str) -> Any:
    if name == "document_type":
        return ex.document_type
    if name == "total":
        return None if ex.total.value is None else str(ex.total.value)
    value = ex.fields[name].value  # type: ignore[index]
    return value.date().isoformat() if name == "date" and value else value


def _truth(truth: InvoiceRecord, name: str) -> Any:
    return {
        "number": truth.number,
        "date": truth.issued.date().isoformat(),
        "customer": truth.customer_id,
        "country": truth.country,
        "document_type": "credit_note" if truth.credit_note else "invoice",
        "total": str(truth.total),
    }[name]


def summarise(results: list[Comparison]) -> dict[str, Any]:
    """Accuracy figures over a group of documents (all as percentages, one decimal)."""
    n = len(results)
    if n == 0:
        return {"documents": 0}

    def pct(num: float, den: float) -> float | None:
        return round(100 * num / den, 1) if den else None

    truth_lines = sum(r.truth_lines for r in results)
    read_lines = sum(r.read_lines for r in results)
    paired = sum(r.paired for r in results)
    wrong = [r for r in results if not r.exact]
    right = [r for r in results if r.exact]
    return {
        "documents": n,
        "exact": pct(len(right), n),
        "header": {k: pct(sum(r.header[k] for r in results), n) for k in HEADER},
        "line_recall": pct(paired, truth_lines),
        "line_precision": pct(paired, read_lines),
        "line_fields": {
            k: pct(sum(r.line_fields[k] for r in results), truth_lines) for k in LINE_FIELDS
        },
        "lines_exact": pct(sum(r.lines_exact for r in results), truth_lines),
        "flagged": pct(sum(r.needs_review for r in results), n),
        "caught": pct(sum(r.needs_review for r in wrong), len(wrong)),
        "false_alarms": pct(sum(r.needs_review for r in right), len(right)),
        "silently_wrong": sum(1 for r in wrong if not r.needs_review),
        "wrong": len(wrong),
    }


# --------------------------------------------------------------------------- reports
def field_report(ex: Extraction, truth: InvoiceRecord) -> dict[str, Any]:
    """Each value read next to the record's, with a verdict: what the demo shows."""
    c = compare(ex, truth)
    header = {
        name: {"read": _shown(ex, name), "record": _truth(truth, name), "correct": ok}
        for name, ok in c.header.items()
    }
    pairs = _pairs(ex.lines, truth.lines)
    lines = [
        {"read": i, "record": j, "fields": _same(ex.lines[i], truth.lines[j]),
         "expected": truth.lines[j].to_json()}
        for i, j in pairs
    ]  # fmt: skip
    paired_read = {i for i, _ in pairs}
    paired_truth = {j for _, j in pairs}
    return {
        "exact": c.exact,
        "header": header,
        "lines": lines,
        "missing": [ln.to_json() for j, ln in enumerate(truth.lines) if j not in paired_truth],
        "extra": [i for i in range(len(ex.lines)) if i not in paired_read],
    }


@dataclass(slots=True)
class DocumentResult:
    id: str
    split: str
    scanned: bool
    style: int
    lines: int
    credit_note: bool
    ms: int
    comparison: Comparison

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "split": self.split,
            "scanned": self.scanned,
            "style": self.style,
            "lines": self.lines,
            "credit_note": self.credit_note,
            "ms": self.ms,
            **self.comparison.to_json(),
        }


def run_documents(
    docs: list[EvalDocument],
    *,
    read: Callable[[bytes], ReadResult] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> list[DocumentResult]:
    """Render, read and extract every document, and compare it with its record. ``read``
    defaults to reading in this process (the documents are generated here); the server
    passes the isolated reader, so the times are those a visitor's run would take."""
    from reluai_docs.invoices.extract import extract_invoice
    from reluai_docs.invoices.render import document_pdf
    from reluai_docs.pdfread import ReadLimits, read_pdf

    limits = ReadLimits(segments=True, max_pages=6, max_ocr_pages=6)
    reader = read or (lambda pdf: read_pdf(pdf, limits))
    out: list[DocumentResult] = []
    for k, doc in enumerate(docs):
        if progress:
            progress(k, len(docs))
        pdf = document_pdf(doc)
        t = time.perf_counter()
        ex = extract_invoice(reader(pdf).pages)
        ms = round((time.perf_counter() - t) * 1000)
        out.append(
            DocumentResult(
                id=doc.id,
                split=doc.split,
                scanned=doc.scanned,
                style=doc.style,
                lines=len(doc.invoice.lines),
                credit_note=doc.invoice.credit_note,
                ms=ms,
                comparison=compare(ex, doc.invoice),
            )
        )
    return out


def _percentile(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def summarise_run(results: list[DocumentResult]) -> dict[str, Any]:
    """Summaries for every split and variant ("dev.text", "held_out.scan", ...) and all."""
    groups: dict[str, list[DocumentResult]] = {"all": list(results)}
    for r in results:
        groups.setdefault(f"{r.split}.{'scan' if r.scanned else 'text'}", []).append(r)
        groups.setdefault("scan" if r.scanned else "text", []).append(r)
    out: dict[str, Any] = {}
    for name, rs in groups.items():
        summary = summarise([r.comparison for r in rs])
        times = [r.ms for r in rs]
        summary["median_ms"] = _percentile(times, 0.5)
        summary["p95_ms"] = _percentile(times, 0.95)
        out[name] = summary
    return out
