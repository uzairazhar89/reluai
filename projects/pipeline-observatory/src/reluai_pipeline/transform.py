"""Shape validated rows into warehouse records."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import pandas as pd

SEP = "\x1f"


@dataclass(slots=True)
class Transformed:
    lines: pd.DataFrame
    invoices: pd.DataFrame
    key_collisions: int  # rows that became identical after normalisation


def line_key(df: pd.DataFrame) -> pd.Series:
    """Stable identity for a source line: SHA-256 (truncated) of its identifying fields.

    Re-processing the same drop yields the same keys, which is what makes loads idempotent.
    """
    parts = (
        df["invoice"]
        + SEP
        + df["stock_code_raw"]
        + SEP
        + df["description"].fillna("")
        + SEP
        + df["quantity"].astype("string")
        + SEP
        + df["unit_price"].map(lambda p: f"{p:.3f}")
        + SEP
        + df["invoiced_at"].dt.strftime("%Y-%m-%d %H:%M:%S")
        + SEP
        + df["customer_id"].astype("string").fillna("")
        + SEP
        + df["country"].fillna("")
    )
    keys: pd.Series = parts.map(lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest()[:32])
    return keys


def transform(accepted: pd.DataFrame) -> Transformed:
    lines = accepted.copy()
    lines["line_key"] = line_key(lines)
    collisions = int(lines["line_key"].duplicated().sum())
    lines = lines.drop_duplicates("line_key", keep="first")
    lines["line_total"] = (lines["quantity"].astype("float64") * lines["unit_price"]).round(3)

    invoices = (
        lines.sort_values("line_number")
        .drop_duplicates("invoice", keep="first")[
            ["invoice", "customer_id", "country", "invoiced_at", "kind"]
        ]
        .reset_index(drop=True)
    )
    return Transformed(
        lines=lines.reset_index(drop=True), invoices=invoices, key_collisions=collisions
    )
