"""Real invoices from UCI Online Retail II, and the evaluation set drawn from them.

The retailer's invoices exist only as table rows; rendering them (``render``) gives
documents whose every field is known exactly, so extraction accuracy is measured against
the records rather than estimated.

The set is drawn reproducibly (fixed seed) from invoices that make a coherent document:
one date, customer and country per invoice, prices in whole pence, and only products,
postage, carriage and manual lines. Administrative entries (bad-debt adjustments, bank
charges, marketplace fees, test products) and gift vouchers, whose descriptions name the
retailer's shop, are left out. Selection is stratified by length, and credit notes
(cancellations, with negative quantities) and invoices without a customer ID are included
on purpose, because they are the cases an extractor gets wrong.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any, Literal

Split = Literal["dev", "held_out"]
PENNY = Decimal("0.01")

# Line-count bands and how many invoices each split takes from each band.
BANDS: tuple[tuple[int, int, int], ...] = ((1, 5, 10), (6, 15, 12), (16, 30, 12), (31, 60, 6))
CREDIT_NOTES = 4  # per split, on top of the bands
NO_CUSTOMER = 4  # per split, on top of the bands
_KEEP_SPECIAL = {"POST", "DOT", "C2", "M"}  # postage, carriage, manual: ordinary lines


def money(value: Decimal | float | str) -> Decimal:
    return Decimal(str(value)).quantize(PENNY, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class InvoiceLine:
    stock_code: str
    description: str
    quantity: int
    unit_price: Decimal

    @property
    def amount(self) -> Decimal:
        return money(self.unit_price * self.quantity)

    def to_json(self) -> dict[str, Any]:
        return {
            "stock_code": self.stock_code,
            "description": self.description,
            "quantity": self.quantity,
            "unit_price": str(self.unit_price),
            "amount": str(self.amount),
        }


@dataclass(frozen=True, slots=True)
class InvoiceRecord:
    number: str  # "489434", or "C489449" for a cancellation (credit note)
    issued: datetime
    customer_id: int | None
    country: str
    lines: tuple[InvoiceLine, ...]

    @property
    def credit_note(self) -> bool:
        return self.number.startswith("C")

    @property
    def total(self) -> Decimal:
        return money(sum((ln.amount for ln in self.lines), Decimal(0)))

    def to_json(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "issued": self.issued.isoformat(timespec="minutes"),
            "customer_id": self.customer_id,
            "country": self.country,
            "credit_note": self.credit_note,
            "total": str(self.total),
            "lines": [ln.to_json() for ln in self.lines],
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> InvoiceRecord:
        return cls(
            number=str(data["number"]),
            issued=datetime.fromisoformat(data["issued"]),
            customer_id=None if data["customer_id"] is None else int(data["customer_id"]),
            country=str(data["country"]),
            lines=tuple(
                InvoiceLine(
                    str(ln["stock_code"]),
                    str(ln["description"]),
                    int(ln["quantity"]),
                    Decimal(str(ln["unit_price"])),
                )
                for ln in data["lines"]
            ),
        )


@dataclass(frozen=True, slots=True)
class EvalDocument:
    """One document of the evaluation set: an invoice, the layout it is drawn in, and
    whether it is a simulated scan."""

    id: str  # "489434-s3" or "489434-s3-scan"
    split: Split
    invoice: InvoiceRecord
    style: int  # layout seed (see ``render.style_for``)
    scanned: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "split": self.split,
            "style": self.style,
            "scanned": self.scanned,
            "invoice": self.invoice.to_json(),
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> EvalDocument:
        return cls(
            id=str(data["id"]),
            split=data["split"],
            invoice=InvoiceRecord.from_json(data["invoice"]),
            style=int(data["style"]),
            scanned=bool(data["scanned"]),
        )


# --------------------------------------------------------------------------- loading
def _eligible(df: Any) -> tuple[Any, Any]:
    """Invoices that make a coherent, ordinary document (see the module docstring), and
    their line counts."""
    import pandas as pd

    df = df.copy()
    df["description"] = df["description"].fillna("").astype(str).str.split().str.join(" ")
    special = ~df["stock_code"].str.fullmatch(r"\d{5}[A-Za-z]{0,2}").fillna(False)
    df["_bad"] = special & ~df["stock_code"].isin(_KEEP_SPECIAL)
    df["_odd_price"] = ((df["price"] * 100).round(6) % 1 != 0) | (df["price"] <= 0)
    df["_empty"] = df["description"] == ""
    df["_no_customer"] = df["customer_id"].isna()
    per = df.groupby("invoice").agg(
        dates=("invoice_date", "nunique"),
        customers=("customer_id", "nunique"),
        no_customer=("_no_customer", "sum"),
        countries=("country", "nunique"),
        bad=("_bad", "any"),
        odd_price=("_odd_price", "any"),
        blank=("_empty", "any"),
        lines=("stock_code", "size"),
    )
    one_customer = ((per.customers == 1) & (per.no_customer == 0)) | (
        (per.customers == 0) & (per.no_customer == per.lines)
    )
    ok = per[
        (per.dates == 1)
        & one_customer
        & (per.countries == 1)
        & ~per.bad
        & ~per.odd_price
        & ~per["blank"]
        & (per.lines <= 60)
        & pd.Series(per.index, index=per.index).str.fullmatch(r"C?\d{6}")
    ]
    keep = [c for c in df.columns if not c.startswith("_")]
    return df.loc[df["invoice"].isin(ok.index), keep], ok["lines"]


def _record(rows: Any) -> InvoiceRecord:
    import pandas as pd

    first = rows.iloc[0]
    customer = first["customer_id"]
    return InvoiceRecord(
        number=str(first["invoice"]),
        issued=first["invoice_date"].to_pydatetime(),
        customer_id=None if pd.isna(customer) else int(customer),
        country=str(first["country"]),
        lines=tuple(
            InvoiceLine(
                str(r.stock_code),
                str(r.description),
                int(r.quantity),
                money(r.price),
            )
            for r in rows.itertuples()
        ),
    )


def _pick(rng: random.Random, pool: list[str], taken: set[str], n: int) -> list[str]:
    free = [x for x in pool if x not in taken]
    chosen = rng.sample(free, min(n, len(free)))
    taken.update(chosen)
    return chosen


def select_invoices(parquet: Path, *, seed: int = 20091201) -> dict[Split, list[InvoiceRecord]]:
    """Draw the dev and held-out invoices (disjoint) from the canonical Parquet file."""
    import pandas as pd

    df = pd.read_parquet(parquet)
    rows, lines = _eligible(df)
    rng = random.Random(seed)  # noqa: S311 - reproducible choices, not security
    numbers = sorted(lines.index)
    credit = [n for n in numbers if n.startswith("C")]
    no_customer_ids = set(rows.loc[rows["customer_id"].isna(), "invoice"])
    sales = [n for n in numbers if not n.startswith("C")]
    no_customer = [n for n in sales if n in no_customer_ids]
    with_customer = [n for n in sales if n not in no_customer_ids]
    taken: set[str] = set()
    chosen: dict[Split, list[str]] = {"dev": [], "held_out": []}
    for split in ("dev", "held_out"):
        for lo, hi, count in BANDS:
            band = [n for n in with_customer if lo <= int(lines[n]) <= hi]
            chosen[split] += _pick(rng, band, taken, count)
        chosen[split] += _pick(rng, credit, taken, CREDIT_NOTES)
        chosen[split] += _pick(rng, no_customer, taken, NO_CUSTOMER)
    grouped = rows[rows["invoice"].isin(taken)].groupby("invoice", sort=False)
    by_number = {str(k): _record(g) for k, g in grouped}
    return {split: [by_number[n] for n in chosen[split]] for split in ("dev", "held_out")}


# --------------------------------------------------------------------------- the set
DEV_STYLES = tuple(range(1, 13))  # layout seeds used while developing the extractor
HELD_OUT_STYLES = tuple(range(1001, 1013))  # never looked at during development
SCANS_PER_SPLIT = 14


def evaluation_set(
    invoices: dict[Split, list[InvoiceRecord]], *, seed: int = 7
) -> list[EvalDocument]:
    """Every invoice as a text PDF in its split's layouts (cycled), plus a fixed share of
    them again as simulated scans, in a different layout from the same split."""
    rng = random.Random(seed)  # noqa: S311 - reproducible choices, not security
    docs: list[EvalDocument] = []
    for split, styles in (("dev", DEV_STYLES), ("held_out", HELD_OUT_STYLES)):
        records = invoices[split]  # type: ignore[index]
        for i, inv in enumerate(records):
            style = styles[i % len(styles)]
            docs.append(EvalDocument(f"{inv.number}-s{style}", split, inv, style, False))  # type: ignore[arg-type]
        # Scans: short and medium invoices (OCR is limited to a few pages per document).
        short = [inv for inv in records if len(inv.lines) <= 30]
        for j, inv in enumerate(rng.sample(short, min(SCANS_PER_SPLIT, len(short)))):
            style = styles[(j * 5 + 3) % len(styles)]
            docs.append(
                EvalDocument(f"{inv.number}-s{style}-scan", split, inv, style, True)  # type: ignore[arg-type]
            )
    return docs


def write_set(docs: Iterable[EvalDocument], path: Path) -> None:
    payload = {"version": 1, "documents": [d.to_json() for d in docs]}
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def load_set(path: Path) -> list[EvalDocument]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [EvalDocument.from_json(d) for d in data["documents"]]
