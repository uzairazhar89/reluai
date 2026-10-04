"""Idempotent, transactional load into the ``retail`` warehouse using COPY + upserts.

Everything happens in the caller's transaction: if any statement or the reconciliation
check fails, nothing from this drop becomes visible.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, cast

import pandas as pd
import psycopg
from sqlalchemy import CursorResult, text
from sqlalchemy.orm import Session


class ReconciliationError(RuntimeError):
    """Rows in the warehouse do not match the batch after loading."""


@dataclass(frozen=True, slots=True)
class LoadResult:
    lines_inserted: int
    lines_unchanged: int
    invoices_inserted: int
    customers_upserted: int
    products_upserted: int


def _driver(session: Session) -> psycopg.Connection[tuple[object, ...]]:
    conn = session.connection().connection.driver_connection
    assert isinstance(conn, psycopg.Connection)  # noqa: S101 - psycopg is the only driver
    return conn


def _copy(
    conn: psycopg.Connection[tuple[object, ...]],
    table: str,
    columns: list[str],
    rows: list[tuple[object, ...]],
) -> None:
    with (
        conn.cursor() as cur,
        cur.copy(
            f"COPY {table} ({', '.join(columns)}) FROM STDIN"  # identifiers are constants
        ) as copy,
    ):
        for row in rows:
            copy.write_row(row)


def _column_rows(df: pd.DataFrame, columns: list[str]) -> list[tuple[object, ...]]:
    """Row tuples for COPY, with pandas missing values converted to SQL NULL."""
    cols = [df[c].astype(object).where(df[c].notna(), None).tolist() for c in columns]
    return list(zip(*cols, strict=True))


def _rowcount(result: object) -> int:
    """Rows affected by a DML statement (SQLAlchemy returns a CursorResult for these)."""
    return int(cast("CursorResult[Any]", result).rowcount)


_TEMP_TABLES = (
    "CREATE TEMP TABLE tmp_customer (customer_id int, country text, first_seen date)"
    " ON COMMIT DROP",
    "CREATE TEMP TABLE tmp_product (stock_code text, description text, line_type text,"
    " first_seen date, last_seen date) ON COMMIT DROP",
    "CREATE TEMP TABLE tmp_invoice (invoice_no text, customer_id int, country text,"
    " invoiced_at timestamp, kind text) ON COMMIT DROP",
    "CREATE TEMP TABLE tmp_line (line_key text, invoice_no text, stock_code text,"
    " description text, quantity int, unit_price numeric(12,3), line_total numeric(14,3),"
    " line_type text) ON COMMIT DROP",
)


def load_batch(
    session: Session,
    *,
    run_id: uuid.UUID,
    drop_key: str,
    lines: pd.DataFrame,
    invoices: pd.DataFrame,
    customers: dict[int, tuple[str, date]],
    catalogue: list[dict[str, str]],
) -> LoadResult:
    conn = _driver(session)
    for ddl in _TEMP_TABLES:
        session.execute(text(ddl))

    _copy(
        conn,
        "tmp_customer",
        ["customer_id", "country", "first_seen"],
        [(cid, country, seen) for cid, (country, seen) in customers.items()],
    )
    _copy(
        conn,
        "tmp_product",
        ["stock_code", "description", "line_type", "first_seen", "last_seen"],
        [
            (
                p["stock_code"],
                p["description"][:200],
                p["line_type"],
                date.fromisoformat(p["first_seen"]),
                date.fromisoformat(p["last_seen"]),
            )
            for p in catalogue
        ],
    )
    _copy(
        conn,
        "tmp_invoice",
        ["invoice_no", "customer_id", "country", "invoiced_at", "kind"],
        _column_rows(invoices, ["invoice", "customer_id", "country", "invoiced_at", "kind"]),
    )
    line_rows = pd.DataFrame(
        {
            "line_key": lines["line_key"],
            "invoice_no": lines["invoice"],
            "stock_code": lines["stock_code"],
            "description": lines["description"].fillna("").str.slice(0, 200),
            "quantity": lines["quantity"].astype("int64"),
            "unit_price": lines["unit_price"].round(3),
            "line_total": lines["line_total"].round(3),
            "line_type": lines["line_type"],
        }
    )
    _copy(
        conn, "tmp_line", list(line_rows.columns), _column_rows(line_rows, list(line_rows.columns))
    )

    customers_upserted = _rowcount(
        session.execute(
            text("""
        INSERT INTO retail.customer (customer_id, country, first_seen)
        SELECT customer_id, country, first_seen FROM tmp_customer
        ON CONFLICT (customer_id) DO UPDATE
          SET country = EXCLUDED.country, first_seen = LEAST(retail.customer.first_seen,
                                                             EXCLUDED.first_seen)
          WHERE retail.customer.country IS DISTINCT FROM EXCLUDED.country
             OR retail.customer.first_seen > EXCLUDED.first_seen
    """)
        )
    )
    products_upserted = _rowcount(
        session.execute(
            text("""
        INSERT INTO retail.product (stock_code, description, line_type, first_seen, last_seen)
        SELECT stock_code, description, line_type, first_seen, last_seen FROM tmp_product
        ON CONFLICT (stock_code) DO UPDATE
          SET description = EXCLUDED.description, line_type = EXCLUDED.line_type,
              first_seen = EXCLUDED.first_seen, last_seen = EXCLUDED.last_seen
          WHERE (retail.product.description, retail.product.line_type,
                 retail.product.first_seen, retail.product.last_seen)
             IS DISTINCT FROM (EXCLUDED.description, EXCLUDED.line_type,
                               EXCLUDED.first_seen, EXCLUDED.last_seen)
    """)
        )
    )
    invoices_inserted = _rowcount(
        session.execute(
            text("""
        INSERT INTO retail.invoice (invoice_no, customer_id, country, invoiced_at, kind,
                                    drop_key, loaded_run_id)
        SELECT invoice_no, customer_id, country, invoiced_at, kind, :drop, :run FROM tmp_invoice
        ON CONFLICT (invoice_no) DO NOTHING
    """),
            {"drop": drop_key, "run": run_id},
        )
    )
    lines_inserted = _rowcount(
        session.execute(
            text("""
        INSERT INTO retail.invoice_line (line_key, invoice_no, stock_code, description,
          quantity, unit_price, line_total, line_type, drop_key, loaded_run_id)
        SELECT line_key, invoice_no, stock_code, description, quantity, unit_price, line_total,
               line_type, :drop, :run FROM tmp_line
        ON CONFLICT (line_key) DO NOTHING
    """),
            {"drop": drop_key, "run": run_id},
        )
    )

    # Reconciliation: every line in the batch must now exist in the warehouse.
    batch_rows, present = session.execute(
        text("""
        SELECT (SELECT count(*) FROM tmp_line),
               (SELECT count(*) FROM tmp_line t JOIN retail.invoice_line l USING (line_key))
    """)
    ).one()
    if batch_rows != present or batch_rows != len(lines):
        raise ReconciliationError(
            f"batch has {len(lines)} lines, staged {batch_rows}, warehouse holds {present}"
        )

    return LoadResult(
        lines_inserted=int(lines_inserted),
        lines_unchanged=int(len(lines) - lines_inserted),
        invoices_inserted=int(invoices_inserted),
        customers_upserted=int(customers_upserted),
        products_upserted=int(products_upserted),
    )
