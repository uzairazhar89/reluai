"""Validation rules, reason codes and line classification.

Every rule here comes from profiling the real dataset (see docs in the project README):
for example, all 3,457 negative-quantity rows that are not cancellations have a zero price
and no customer — they are stock write-offs ("damages", "check", "missing"), not sales.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

import pandas as pd

INVOICE_RE = r"^[CA]?\d{6}$"
_LOWER_SUFFIX_CODE = re.compile(r"^\d{5}[a-z]+$")


class Severity(StrEnum):
    REJECT = "reject"  # row is quarantined and not published
    DROPPED = "dropped"  # exact duplicate copy, removed during de-duplication
    WARN = "warn"  # row is published but flagged


@dataclass(frozen=True, slots=True)
class Reason:
    code: str
    severity: Severity
    label: str
    explanation: str


_REASONS = [
    # structural problems found while parsing the file
    Reason(
        "malformed_row",
        Severity.REJECT,
        "Malformed row",
        "Wrong number of fields — the line is truncated or has unescaped delimiters.",
    ),
    Reason("encoding_error", Severity.REJECT, "Encoding error", "Bytes that are not valid UTF-8."),
    # type and format problems
    Reason("missing_invoice", Severity.REJECT, "Missing invoice number", "Invoice is empty."),
    Reason(
        "bad_invoice_format",
        Severity.REJECT,
        "Invalid invoice number",
        "Invoice numbers are six digits, optionally prefixed with C (cancellation).",
    ),
    Reason(
        "bad_date",
        Severity.REJECT,
        "Unparseable timestamp",
        "InvoiceDate is not a valid 'YYYY-MM-DD HH:MM:SS' timestamp.",
    ),
    Reason(
        "outside_drop_period",
        Severity.REJECT,
        "Outside drop period",
        "The timestamp falls outside the month this drop covers.",
    ),
    Reason(
        "bad_quantity",
        Severity.REJECT,
        "Invalid quantity",
        "Quantity is missing, non-numeric or not a whole number.",
    ),
    Reason("zero_quantity", Severity.REJECT, "Zero quantity", "A line with quantity 0."),
    Reason("bad_price", Severity.REJECT, "Invalid price", "Price is missing or non-numeric."),
    Reason("missing_stock_code", Severity.REJECT, "Missing stock code", "StockCode is empty."),
    Reason(
        "bad_customer_id",
        Severity.REJECT,
        "Invalid customer ID",
        "Customer ID is present but not a whole number.",
    ),
    # business rules
    Reason(
        "test_record",
        Severity.REJECT,
        "Test record",
        "Stock codes starting with TEST are system test entries.",
    ),
    Reason(
        "accounting_adjustment",
        Severity.REJECT,
        "Accounting adjustment",
        "Invoices prefixed A are bad-debt adjustments, not sales.",
    ),
    Reason(
        "stock_adjustment",
        Severity.REJECT,
        "Stock adjustment",
        "Zero-price line with no customer: an inventory write-off or correction "
        "(damaged, missing, re-labelled stock), not a sale.",
    ),
    Reason("negative_price", Severity.REJECT, "Negative price", "Unit price below zero."),
    Reason(
        "cancellation_sign_mismatch",
        Severity.REJECT,
        "Cancellation sign mismatch",
        "Cancellations (prefix C) must have negative quantities and sales positive ones.",
    ),
    # referential integrity against the reference sources
    Reason(
        "unknown_product",
        Severity.REJECT,
        "Unknown product",
        "StockCode is not in the product catalogue.",
    ),
    Reason(
        "unknown_customer",
        Severity.REJECT,
        "Unknown customer",
        "Customer ID is not in the CRM customer register.",
    ),
    # de-duplication
    Reason(
        "duplicate_line",
        Severity.DROPPED,
        "Duplicate line",
        "Exact copy of another line in the same drop (identical in every field).",
    ),
    # warnings: published but flagged
    Reason(
        "missing_customer_id",
        Severity.WARN,
        "No customer ID",
        "Guest or unidentified customer; kept because the sale is real.",
    ),
    Reason(
        "zero_price_line",
        Severity.WARN,
        "Zero-price line",
        "Free item on a customer invoice (e.g. a replacement or sample).",
    ),
    Reason(
        "extreme_quantity",
        Severity.WARN,
        "Extreme quantity",
        "Absolute quantity of 10,000 or more.",
    ),
    Reason(
        "stock_code_normalised",
        Severity.WARN,
        "Stock code normalised",
        "Lower-case variant (e.g. 85123a) mapped to the catalogue code (85123A).",
    ),
    Reason(
        "description_variant",
        Severity.WARN,
        "Description differs from catalogue",
        "The line's description differs from the catalogue's canonical one.",
    ),
]
REASONS: dict[str, Reason] = {r.code: r for r in _REASONS}

# Priority order for row-level rejection rules (first match wins).
REJECT_ORDER = [r.code for r in _REASONS if r.severity is Severity.REJECT]

# ------------------------------------------------------------------ line classification
_FIXED_TYPES = {
    "POST": "shipping",
    "DOT": "shipping",
    "C2": "shipping",
    "C3": "shipping",
    "D": "discount",
    "M": "manual",
    "S": "sample",
    "BANK CHARGES": "fee",
    "AMAZONFEE": "fee",
    "CRUK": "fee",
    "ADJUST": "adjustment",
    "ADJUST2": "adjustment",
    "GIFT": "voucher",
    "B": "accounting",
}
LINE_TYPES = [
    "product",
    "shipping",
    "discount",
    "manual",
    "sample",
    "fee",
    "adjustment",
    "voucher",
    "accounting",
]


def normalise_stock_code(code: str) -> str:
    code = code.strip()
    if _LOWER_SUFFIX_CODE.match(code) or code == "m":
        return code.upper()
    return code


def classify_line_type(stock_code: str) -> str:
    code = stock_code.strip()
    upper = code.upper()
    if upper in _FIXED_TYPES:
        return _FIXED_TYPES[upper]
    if code.lower().startswith("gift_"):
        return "voucher"
    return "product"


def first_reject_reason(masks: dict[str, pd.Series], index: pd.Index) -> pd.Series:
    """Combine per-rule boolean masks into one reason code per row (or <NA>), by priority."""
    reason = pd.Series(pd.NA, index=index, dtype="string")
    for code in REJECT_ORDER:
        mask = masks.get(code)
        if mask is None:
            continue
        reason = reason.mask(reason.isna() & mask.fillna(False).astype(bool), code)
    return reason
