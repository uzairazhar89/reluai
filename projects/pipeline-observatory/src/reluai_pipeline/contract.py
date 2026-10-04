"""The data contract for monthly invoice drops: structure, parsing and type coercion.

Parsing is line-by-line so a single bad line (truncated, wrong delimiter count, invalid
bytes) is quarantined with its line number instead of failing the whole file.
"""

from __future__ import annotations

import csv
import gzip
from dataclasses import dataclass, field

import pandas as pd

from reluai_pipeline.rules import INVOICE_RE

RAW_COLUMNS: tuple[str, ...] = (
    "Invoice",
    "StockCode",
    "Description",
    "Quantity",
    "InvoiceDate",
    "Price",
    "Customer ID",
    "Country",
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class SchemaMismatchError(ValueError):
    def __init__(self, found: list[str]) -> None:
        super().__init__(f"header {found} does not match contract {list(RAW_COLUMNS)}")
        self.found = found


@dataclass(slots=True)
class StructuralIssue:
    line_number: int
    reason_code: str  # malformed_row | encoding_error
    raw_text: str


@dataclass(slots=True)
class ParsedDrop:
    records: pd.DataFrame  # one string column per RAW_COLUMNS entry + line_number
    issues: list[StructuralIssue] = field(default_factory=list)

    @property
    def rows_read(self) -> int:
        return len(self.records) + len(self.issues)


def read_drop_bytes(path_bytes: bytes) -> bytes:
    """Transparently decompress gzip drops."""
    if path_bytes[:2] == b"\x1f\x8b":
        return gzip.decompress(path_bytes)
    return path_bytes


def parse_drop(data: bytes) -> ParsedDrop:
    lines = read_drop_bytes(data).split(b"\n")
    header_text = lines[0].rstrip(b"\r").decode("utf-8-sig", errors="replace")
    header = next(csv.reader([header_text]))
    if [h.strip() for h in header] != list(RAW_COLUMNS):
        raise SchemaMismatchError(header)

    rows: list[list[str]] = []
    numbers: list[int] = []
    issues: list[StructuralIssue] = []
    width = len(RAW_COLUMNS)
    for number, raw_line in enumerate(lines[1:], start=2):
        raw = raw_line.rstrip(b"\r")
        if not raw.strip():
            continue
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            issues.append(
                StructuralIssue(number, "encoding_error", raw.decode("utf-8", errors="replace"))
            )
            continue
        fields = next(csv.reader([text]))
        if len(fields) != width:
            issues.append(StructuralIssue(number, "malformed_row", text))
            continue
        rows.append(fields)
        numbers.append(number)

    records = pd.DataFrame(rows, columns=list(RAW_COLUMNS), dtype="string")
    records["line_number"] = pd.Series(numbers, dtype="int64")
    return ParsedDrop(records=records, issues=issues)


@dataclass(slots=True)
class TypedRows:
    frame: pd.DataFrame
    type_masks: dict[str, pd.Series]


def coerce(records: pd.DataFrame) -> TypedRows:
    """Coerce string fields to typed columns; returns a mask per type rule."""

    def clean(col: str) -> pd.Series:
        s = records[col].str.strip()
        return s.mask(s == "")

    invoice = clean("Invoice")
    stock = clean("StockCode")
    description = clean("Description").str.replace(r"\s+", " ", regex=True)

    qty_num = pd.to_numeric(clean("Quantity"), errors="coerce")
    bad_qty = qty_num.isna() | (qty_num % 1 != 0)
    dates = pd.to_datetime(clean("InvoiceDate"), format=DATE_FORMAT, errors="coerce")
    price = pd.to_numeric(clean("Price"), errors="coerce").astype("float64")
    cust_raw = clean("Customer ID")
    cust_num = pd.to_numeric(cust_raw, errors="coerce")
    bad_cust = cust_raw.notna() & (cust_num.isna() | (cust_num % 1 != 0))

    frame = pd.DataFrame(
        {
            "line_number": records["line_number"],
            "invoice": invoice,
            "stock_code_raw": stock,
            "description": description,
            "quantity": qty_num.where(~bad_qty).astype("Float64").astype("Int64"),
            "invoiced_at": dates,
            "unit_price": price,
            "customer_id": cust_num.where(~bad_cust).astype("Float64").astype("Int64"),
            "country": clean("Country"),
        }
    )
    masks = {
        "missing_invoice": invoice.isna(),
        "bad_invoice_format": invoice.notna() & ~invoice.fillna("").str.match(INVOICE_RE),
        "bad_date": dates.isna(),
        "bad_quantity": bad_qty,
        "zero_quantity": (frame["quantity"] == 0).fillna(False),
        "bad_price": price.isna(),
        "missing_stock_code": stock.isna(),
        "bad_customer_id": bad_cust,
    }
    return TypedRows(frame=frame, type_masks=masks)
