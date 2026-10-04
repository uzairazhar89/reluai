"""Row-level validation: type, business and referential rules, de-duplication, warnings."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import pandas as pd

from reluai_pipeline.contract import RAW_COLUMNS, ParsedDrop, coerce
from reluai_pipeline.rules import (
    REASONS,
    Severity,
    classify_line_type,
    first_reject_reason,
    normalise_stock_code,
)


@dataclass(slots=True)
class ReferenceData:
    """Reference sources the drop is validated against."""

    catalogue: dict[str, str]  # stock_code -> canonical description
    customers: set[int]


@dataclass(slots=True)
class ValidationResult:
    accepted: pd.DataFrame
    quarantine: pd.DataFrame  # line_number, reason_code, severity, raw (dict)
    rows_read: int
    reject_counts: Counter[str] = field(default_factory=Counter)
    warning_counts: Counter[str] = field(default_factory=Counter)
    rows_deduplicated: int = 0
    rows_warned: int = 0
    rows_outside_period: int = 0

    @property
    def rows_rejected(self) -> int:
        return sum(self.reject_counts.values())


def _raw_dicts(records: pd.DataFrame, positions: pd.Index) -> list[dict[str, str | None]]:
    subset = records.loc[positions, list(RAW_COLUMNS)]
    return [
        {str(k): (None if pd.isna(v) else str(v)) for k, v in row.items()}
        for row in subset.to_dict(orient="records")
    ]


def validate(parsed: ParsedDrop, *, period: pd.Period, refs: ReferenceData) -> ValidationResult:
    typed = coerce(parsed.records)
    df = typed.frame
    masks = dict(typed.type_masks)

    invoice = df["invoice"].fillna("")
    qty = df["quantity"]
    price = df["unit_price"]
    customer_missing = df["customer_id"].isna()
    df["stock_code"] = df["stock_code_raw"].fillna("").map(normalise_stock_code)

    in_period = df["invoiced_at"].dt.to_period("M") == period
    masks["outside_drop_period"] = df["invoiced_at"].notna() & ~in_period
    masks["test_record"] = df["stock_code"].str.upper().str.startswith("TEST")
    masks["accounting_adjustment"] = invoice.str.startswith("A")
    masks["stock_adjustment"] = (price == 0) & customer_missing
    masks["negative_price"] = price < 0
    is_cancel = invoice.str.startswith("C")
    masks["cancellation_sign_mismatch"] = (is_cancel & (qty > 0)) | (~is_cancel & (qty < 0))
    masks["unknown_product"] = df["stock_code_raw"].notna() & ~df["stock_code"].isin(
        refs.catalogue.keys()
    )
    masks["unknown_customer"] = ~customer_missing & ~df["customer_id"].isin(refs.customers)

    reason = first_reject_reason(masks, df.index)
    rejected = reason.notna()

    # De-duplicate exact copies among rows that passed every rule.
    raw_fields = parsed.records[list(RAW_COLUMNS)]
    dup = raw_fields.duplicated(keep="first") & ~rejected

    quarantine_parts: list[pd.DataFrame] = []
    if parsed.issues:
        quarantine_parts.append(
            pd.DataFrame(
                {
                    "line_number": [i.line_number for i in parsed.issues],
                    "reason_code": [i.reason_code for i in parsed.issues],
                    "severity": Severity.REJECT.value,
                    "raw": [{"line": i.raw_text[:500]} for i in parsed.issues],
                }
            )
        )
    for codes, severity, mask in (
        (reason, Severity.REJECT, rejected),
        (None, Severity.DROPPED, dup),
    ):
        idx = df.index[mask]
        if len(idx):
            quarantine_parts.append(
                pd.DataFrame(
                    {
                        "line_number": df.loc[idx, "line_number"].to_numpy(),
                        "reason_code": (
                            codes.loc[idx].to_numpy() if codes is not None else "duplicate_line"
                        ),
                        "severity": severity.value,
                        "raw": _raw_dicts(parsed.records, idx),
                    }
                )
            )
    quarantine = (
        pd.concat(quarantine_parts, ignore_index=True)
        if quarantine_parts
        else pd.DataFrame(columns=["line_number", "reason_code", "severity", "raw"])
    )

    reject_counts: Counter[str] = Counter(i.reason_code for i in parsed.issues)
    reject_counts.update({str(k): int(n) for k, n in reason[rejected].value_counts().items()})

    accepted = df[~rejected & ~dup].copy()
    canonical = accepted["stock_code"].map(refs.catalogue).astype("string")
    accepted["description"] = accepted["description"].fillna(canonical)
    accepted["line_type"] = accepted["stock_code"].map(classify_line_type)
    accepted["kind"] = (
        accepted["invoice"].str.startswith("C").map({True: "cancellation", False: "sale"})
    )

    warn_masks = {
        "missing_customer_id": accepted["customer_id"].isna(),
        "zero_price_line": accepted["unit_price"] == 0,
        "extreme_quantity": accepted["quantity"].abs() >= 10_000,
        "stock_code_normalised": accepted["stock_code"] != accepted["stock_code_raw"],
        "description_variant": accepted["description"].str.upper() != canonical.str.upper(),
    }
    warning_counts: Counter[str] = Counter()
    any_warn = pd.Series(False, index=accepted.index)
    for code, mask in warn_masks.items():
        m = mask.fillna(False).astype(bool)
        assert REASONS[code].severity is Severity.WARN  # noqa: S101 - registry invariant
        if int(m.sum()):
            warning_counts[code] = int(m.sum())
        any_warn |= m

    return ValidationResult(
        accepted=accepted.reset_index(drop=True),
        quarantine=quarantine,
        rows_read=parsed.rows_read,
        reject_counts=reject_counts,
        warning_counts=warning_counts,
        rows_deduplicated=int(dup.sum()),
        rows_warned=int(any_warn.sum()),
        rows_outside_period=int(masks["outside_drop_period"].sum()),
    )
