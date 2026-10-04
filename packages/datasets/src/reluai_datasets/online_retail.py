"""UCI "Online Retail II": loading, normalisation and content verification.

The canonical archive (an Excel workbook with two yearly sheets) and the development mirror
(an R data file) are both normalised to the same table and must produce the same content
fingerprint, so either source yields byte-identical downstream results.
"""

from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pandas as pd

from reluai_datasets.manifest import ContentChecks

DATASET_ID = "online-retail-ii"

CANONICAL_COLUMNS = [
    "invoice",
    "stock_code",
    "description",
    "quantity",
    "invoice_date",
    "price",
    "customer_id",
    "country",
]

_RENAME = {
    "Invoice": "invoice",
    "InvoiceNo": "invoice",
    "StockCode": "stock_code",
    "Description": "description",
    "Quantity": "quantity",
    "InvoiceDate": "invoice_date",
    "Price": "price",
    "UnitPrice": "price",
    "Customer ID": "customer_id",
    "CustomerID": "customer_id",
    "Country": "country",
}


class ContentMismatchError(ValueError):
    """The loaded data does not match the manifest's content checks."""


def _code_str(s: pd.Series) -> pd.Series:
    """Excel may store invoice numbers and stock codes as numbers; normalise to text."""
    out = s.astype("string").str.strip()
    return out.str.replace(r"\.0$", "", regex=True)


def normalise(raw: pd.DataFrame) -> pd.DataFrame:
    df = raw.rename(columns=_RENAME)
    missing = set(CANONICAL_COLUMNS) - set(df.columns)
    if missing:
        raise ContentMismatchError(f"missing columns: {sorted(missing)}")
    df = df[CANONICAL_COLUMNS].copy()
    df["invoice"] = _code_str(df["invoice"])
    df["stock_code"] = _code_str(df["stock_code"])
    desc = df["description"].astype("string").str.strip()
    df["description"] = desc.mask(desc == "")
    df["quantity"] = pd.to_numeric(df["quantity"]).round().astype("int64")
    df["invoice_date"] = pd.to_datetime(df["invoice_date"]).astype("datetime64[s]")
    df["price"] = pd.to_numeric(df["price"]).astype("float64")
    df["customer_id"] = pd.to_numeric(df["customer_id"]).astype("Float64").round().astype("Int64")
    df["country"] = df["country"].astype("string").str.strip()
    return df.reset_index(drop=True)


def read_rda(path: Path) -> pd.DataFrame:
    import pyreadr

    frames = pyreadr.read_r(str(path))
    if len(frames) != 1:
        raise ContentMismatchError(f"expected one table in {path.name}, found {len(frames)}")
    return normalise(next(iter(frames.values())))


def read_uci_zip(path: Path) -> pd.DataFrame:
    """Read the UCI archive: one workbook, two sheets (2009-2010 and 2010-2011)."""
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith(".xlsx")]
        if len(names) != 1:
            raise ContentMismatchError(f"expected one .xlsx in archive, found {names}")
        with zf.open(names[0]) as fh:
            sheets = pd.read_excel(
                fh, sheet_name=None, engine="openpyxl", dtype={"Invoice": str, "StockCode": str}
            )
    return normalise(pd.concat(list(sheets.values()), ignore_index=True))


def fingerprint(df: pd.DataFrame) -> str:
    """Order-independent SHA-256 over a canonical text form of every row (version 1)."""
    sep = "\x1f"
    cust = df["customer_id"].astype("string").fillna("")
    rows = (
        df["invoice"].fillna("")
        + sep
        + df["stock_code"].fillna("")
        + sep
        + df["description"].fillna("")
        + sep
        + df["quantity"].astype("string")
        + sep
        + df["invoice_date"].dt.strftime("%Y-%m-%d %H:%M")
        + sep
        + df["price"].map(lambda p: f"{p:.3f}")
        + sep
        + cust
        + sep
        + df["country"].fillna("")
    )
    h = hashlib.sha256()
    for line in rows.sort_values(ignore_index=True):
        h.update(line.encode("utf-8"))
        h.update(b"\n")
    return h.hexdigest()


def verify(df: pd.DataFrame, checks: ContentChecks) -> str:
    """Raise :class:`ContentMismatchError` unless ``df`` matches ``checks``; returns fingerprint."""
    problems: list[str] = []
    if len(df) != checks.rows:
        problems.append(f"rows {len(df)} != {checks.rows}")
    if list(df.columns) != checks.columns:
        problems.append(f"columns {list(df.columns)} != {checks.columns}")
    lo, hi = df["invoice_date"].min(), df["invoice_date"].max()
    if lo != pd.Timestamp(checks.min_timestamp) or hi != pd.Timestamp(checks.max_timestamp):
        problems.append(f"date range {lo}..{hi} != {checks.min_timestamp}..{checks.max_timestamp}")
    digest = fingerprint(df)
    if digest != checks.content_sha256:
        problems.append(f"content fingerprint {digest} != {checks.content_sha256}")
    if problems:
        raise ContentMismatchError("; ".join(problems))
    return digest
