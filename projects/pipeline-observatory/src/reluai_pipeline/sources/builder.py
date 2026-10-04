"""Derive the pipeline's source systems from the verified Online Retail II table.

Real retailers do not hand over one tidy table, so the demo reproduces three typical
sources — without altering any values:

* ``invoices/YYYY-MM.csv.gz`` — 25 monthly export files in the dataset's original column
  layout (the "file drop" an ERP sends every month);
* ``catalogue/products.json`` — the product master (one canonical description per code);
* ``crm/customers.parquet`` — the customer register served by the mock CRM REST API.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from reluai_core.logging import get_logger
from reluai_pipeline.contract import RAW_COLUMNS
from reluai_pipeline.rules import classify_line_type, normalise_stock_code

BUILDER_VERSION = 1
log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class DropInfo:
    key: str
    file: str
    rows: int
    sha256: str


@dataclass(frozen=True, slots=True)
class SourceIndex:
    builder_version: int
    dataset_content_sha256: str
    drops: list[DropInfo]
    products: int
    customers: int


def _fmt_price(p: float) -> str:
    return f"{p:.3f}".rstrip("0").rstrip(".")


def _drop_bytes(month: pd.DataFrame) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(RAW_COLUMNS)
    cust = month["customer_id"].astype("string").fillna("")
    for row in zip(
        month["invoice"],
        month["stock_code"],
        month["description"].fillna(""),
        month["quantity"],
        month["invoice_date"].dt.strftime("%Y-%m-%d %H:%M:%S"),
        month["price"].map(_fmt_price),
        cust,
        month["country"],
        strict=True,
    ):
        writer.writerow(row)
    # mtime=0 keeps the gzip bytes (and therefore the checksum) reproducible.
    return gzip.compress(buf.getvalue().encode("utf-8"), mtime=0)


def _catalogue(df: pd.DataFrame) -> list[dict[str, str]]:
    codes = df["stock_code"].map(normalise_stock_code)
    keep = ~codes.str.upper().str.startswith("TEST") & (codes != "B")
    sub = df.loc[keep].assign(code=codes[keep])
    sub = sub[sub["description"].notna()].copy()
    # Same whitespace normalisation the pipeline applies to incoming lines.
    sub["description"] = sub["description"].str.replace(r"\s+", " ", regex=True).str.strip()
    # Canonical description: the most frequent one on priced lines (zero-price lines are
    # mostly stock write-offs annotated "damaged", "check", ...).
    priced = sub[sub["price"] > 0]
    pick = priced if not priced.empty else sub
    desc = (
        pick.groupby(["code", "description"])
        .size()
        .rename("n")
        .reset_index()
        .sort_values(["code", "n", "description"], ascending=[True, False, True])
        .drop_duplicates("code")
        .set_index("code")["description"]
    )
    fallback = sub.groupby("code")["description"].agg(lambda s: s.mode().iloc[0])
    dates = sub.groupby("code")["invoice_date"].agg(["min", "max"])
    first_seen = dates["min"].dt.strftime("%Y-%m-%d").to_dict()
    last_seen = dates["max"].dt.strftime("%Y-%m-%d").to_dict()
    return [
        {
            "stock_code": str(code),
            "description": str(desc.get(code, fallback[code])),
            "line_type": classify_line_type(str(code)),
            "first_seen": str(first_seen[code]),
            "last_seen": str(last_seen[code]),
        }
        for code in sorted(dates.index)
    ]


def _customers(df: pd.DataFrame) -> pd.DataFrame:
    known = df[df["customer_id"].notna()]
    country = (
        known.groupby(["customer_id", "country"])
        .size()
        .rename("n")
        .reset_index()
        .sort_values(["customer_id", "n", "country"], ascending=[True, False, True])
        .drop_duplicates("customer_id")
        .set_index("customer_id")["country"]
    )
    first = known.groupby("customer_id")["invoice_date"].min().dt.date
    return pd.DataFrame(
        {
            "customer_id": country.index.astype("int64"),
            "country": country.to_numpy(),
            "first_seen": first.reindex(country.index).to_numpy(),
        }
    )


def build_sources(df: pd.DataFrame, out_dir: Path, *, content_sha256: str) -> SourceIndex:
    (out_dir / "invoices").mkdir(parents=True, exist_ok=True)
    (out_dir / "catalogue").mkdir(parents=True, exist_ok=True)
    (out_dir / "crm").mkdir(parents=True, exist_ok=True)

    drops: list[DropInfo] = []
    months = df["invoice_date"].dt.strftime("%Y-%m")
    for key in sorted(months.unique()):
        data = _drop_bytes(df[months == key])
        name = f"invoices/{key}.csv.gz"
        (out_dir / name).write_bytes(data)
        drops.append(
            DropInfo(
                key=key,
                file=name,
                rows=int((months == key).sum()),
                sha256=hashlib.sha256(data).hexdigest(),
            )
        )

    catalogue = _catalogue(df)
    (out_dir / "catalogue" / "products.json").write_text(
        json.dumps({"generated_from": content_sha256, "products": catalogue}, indent=0),
        encoding="utf-8",
    )
    customers = _customers(df)
    customers.to_parquet(out_dir / "crm" / "customers.parquet", index=False)

    index = SourceIndex(
        builder_version=BUILDER_VERSION,
        dataset_content_sha256=content_sha256,
        drops=drops,
        products=len(catalogue),
        customers=len(customers),
    )
    (out_dir / "index.json").write_text(
        json.dumps(asdict(index), indent=2) + "\n", encoding="utf-8"
    )
    log.info(
        "sources.built",
        drops=len(drops),
        products=len(catalogue),
        customers=len(customers),
        out_dir=str(out_dir),
    )
    return index


def load_index(sources_dir: Path) -> SourceIndex:
    raw = json.loads((sources_dir / "index.json").read_text(encoding="utf-8"))
    raw["drops"] = [DropInfo(**d) for d in raw["drops"]]
    return SourceIndex(**raw)
