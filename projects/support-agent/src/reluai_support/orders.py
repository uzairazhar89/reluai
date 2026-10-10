"""The retailer's real orders, as the support desk sees them.

``build_orders`` turns the verified canonical Parquet into a small read-only DuckDB file:
invoice lines for customers with an ID (a support desk serves account holders), with the
exact duplicate lines from the source export's overlapping sheets removed, as in the data
pipeline project. ``OrderStore`` reads it; every lookup is scoped to one customer.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import duckdb

_BUILD = """
CREATE TABLE line AS
WITH src AS (
    SELECT DISTINCT invoice, stock_code, description, quantity, invoice_date, price,
           customer_id, country
    FROM read_parquet(?)
    WHERE customer_id IS NOT NULL
)
SELECT
    invoice AS invoice_no,
    CAST(row_number() OVER (
        PARTITION BY invoice ORDER BY stock_code, description, quantity, price
    ) AS INTEGER) AS line_no,
    stock_code,
    coalesce(description, '') AS description,
    CAST(quantity AS INTEGER) AS quantity,
    CAST(price AS DECIMAL(12, 2)) AS unit_price,
    CAST(quantity * price AS DECIMAL(14, 2)) AS line_total,
    CAST(invoice_date AS TIMESTAMP) AS invoiced_at,
    CAST(customer_id AS BIGINT) AS customer_id,
    country,
    CASE
        WHEN stock_code IN ('POST', 'DOT', 'C2') OR lower(description) = 'next day carriage'
            THEN 'shipping'
        WHEN stock_code IN ('M', 'm', 'D', 'S', 'BANK CHARGES', 'ADJUST', 'AMAZONFEE', 'B',
                            'CRUK', 'TEST001') OR stock_code LIKE 'gift_%' THEN 'other'
        ELSE 'product'
    END AS kind
FROM src;

CREATE TABLE invoice AS
SELECT
    invoice_no,
    min(invoiced_at) AS invoiced_at,
    any_value(customer_id) AS customer_id,
    any_value(country) AS country,
    CAST(count(*) AS INTEGER) AS lines,
    CAST(sum(quantity) FILTER (WHERE kind = 'product') AS INTEGER) AS units,
    CAST(coalesce(sum(line_total) FILTER (WHERE kind = 'product'), 0) AS DECIMAL(14, 2))
        AS goods_total,
    CAST(coalesce(sum(line_total) FILTER (WHERE kind = 'shipping'), 0) AS DECIMAL(14, 2))
        AS shipping_total,
    CAST(sum(line_total) AS DECIMAL(14, 2)) AS total,
    invoice_no LIKE 'C%' AS is_credit_note
FROM line
GROUP BY invoice_no;

CREATE INDEX ix_line_invoice ON line (invoice_no);
CREATE INDEX ix_invoice_customer ON invoice (customer_id);
"""


def build_orders(canonical_dir: Path, out_dir: Path) -> Path:
    source = canonical_dir / "online-retail-ii.parquet"
    if not source.is_file():
        raise FileNotFoundError(f"canonical dataset not found: {source}")
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "orders.duckdb"
    tmp = out_dir / "orders.duckdb.partial"
    tmp.unlink(missing_ok=True)
    con = duckdb.connect(str(tmp))
    try:
        for statement in _BUILD.split(";\n"):
            if statement.strip():
                con.execute(statement, [str(source)] if "read_parquet(?)" in statement else [])
    finally:
        con.close()
    tmp.replace(target)
    return target


@dataclass(frozen=True, slots=True)
class Line:
    line_no: int
    stock_code: str
    description: str
    quantity: int
    unit_price: float
    line_total: float
    kind: str  # product | shipping | other


@dataclass(frozen=True, slots=True)
class InvoiceHeader:
    invoice_no: str
    invoiced_at: datetime
    customer_id: int
    country: str
    lines: int
    units: int
    goods_total: float
    shipping_total: float
    total: float
    is_credit_note: bool


@dataclass(frozen=True, slots=True)
class Invoice:
    header: InvoiceHeader
    lines: list[Line]


_HEADER_SQL = (
    "SELECT invoice_no, invoiced_at, customer_id, country, lines, coalesce(units, 0), "
    "goods_total, shipping_total, total, is_credit_note FROM invoice"
)


def _header(row: tuple[object, ...]) -> InvoiceHeader:
    return InvoiceHeader(
        invoice_no=str(row[0]),
        invoiced_at=row[1],  # type: ignore[arg-type]
        customer_id=int(row[2]),  # type: ignore[call-overload]
        country=str(row[3]),
        lines=int(row[4]),  # type: ignore[call-overload]
        units=int(row[5]),  # type: ignore[call-overload]
        goods_total=float(row[6]),  # type: ignore[arg-type]
        shipping_total=float(row[7]),  # type: ignore[arg-type]
        total=float(row[8]),  # type: ignore[arg-type]
        is_credit_note=bool(row[9]),
    )


class OrderStore:
    """Read-only access to the snapshot; one shared connection, a cursor per call."""

    _lock = threading.Lock()
    _connections: ClassVar[dict[str, duckdb.DuckDBPyConnection]] = {}

    def __init__(self, path: Path) -> None:
        self.path = path

    def _cursor(self) -> duckdb.DuckDBPyConnection:
        key = str(self.path)
        with self._lock:
            con = self._connections.get(key)
            if con is None:
                if not self.path.is_file():
                    raise FileNotFoundError(f"order snapshot not built: {self.path}")
                con = duckdb.connect(
                    key,
                    read_only=True,
                    config={
                        "enable_external_access": False,
                        "autoload_known_extensions": False,
                        "autoinstall_known_extensions": False,
                        "threads": 1,
                        "memory_limit": "128MB",
                    },
                )
                con.execute("SET lock_configuration = true")
                self._connections[key] = con
            return con.cursor()

    def invoice(self, invoice_no: str) -> Invoice | None:
        cur = self._cursor()
        try:
            row = cur.execute(f"{_HEADER_SQL} WHERE invoice_no = ?", [invoice_no]).fetchone()
            if row is None:
                return None
            lines = cur.execute(
                "SELECT line_no, stock_code, description, quantity, unit_price, line_total, kind "
                "FROM line WHERE invoice_no = ? ORDER BY line_no",
                [invoice_no],
            ).fetchall()
        finally:
            cur.close()
        return Invoice(
            header=_header(row),
            lines=[
                Line(
                    int(r[0]), str(r[1]), str(r[2]), int(r[3]), float(r[4]), float(r[5]), str(r[6])
                )
                for r in lines
            ],
        )

    def customer_invoices(
        self, customer_id: int, *, limit: int = 10, before: datetime | None = None
    ) -> list[InvoiceHeader]:
        cur = self._cursor()
        try:
            rows = cur.execute(
                f"{_HEADER_SQL} WHERE customer_id = ? AND (? IS NULL OR invoiced_at < ?) "
                "ORDER BY invoiced_at DESC, invoice_no DESC LIMIT ?",
                [customer_id, before, before, limit],
            ).fetchall()
        finally:
            cur.close()
        return [_header(r) for r in rows]

    def customer_summary(self, customer_id: int) -> tuple[str, int, datetime, datetime] | None:
        """(country, invoices, first order, last order) for a customer."""
        cur = self._cursor()
        try:
            row = cur.execute(
                "SELECT any_value(country), count(*), min(invoiced_at), max(invoiced_at) "
                "FROM invoice WHERE customer_id = ? AND NOT is_credit_note",
                [customer_id],
            ).fetchone()
        finally:
            cur.close()
        if row is None or not row[1]:
            return None
        return str(row[0]), int(row[1]), row[2], row[3]
