"""Fixtures for the support agent tests.

``orders`` is a small order snapshot built from a generated table in the canonical layout.
Shipment outcomes are derived from invoice numbers, so the generator picks numbers whose
simulated shipment has the outcome each test needs (delivered recently, delivered long
ago, late, lost, still in transit). It is a unit-test fixture only; the real scenarios run
in ``test_real_scenarios.py`` when the verified dataset is available.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd
import pytest

from reluai_retrieval.chunking import chunk_text
from reluai_retrieval.search import Hit
from reluai_support.agent import AgentRuntime, scripted_chain
from reluai_support.orders import InvoiceHeader, OrderStore, build_orders
from reluai_support.policy import POLICY_TEXT
from reluai_support.shipments import shipment_for

AS_OF = date(2011, 12, 10)
CUSTOMER = 50001
OTHER = 50002


@dataclass(frozen=True)
class Fixture:
    store: OrderStore
    invoices: dict[str, str]  # role -> invoice number


def _find(role: str, when: datetime, start: int) -> str:
    for n in range(start, start + 20000):
        header = InvoiceHeader(str(n), when, CUSTOMER, "United Kingdom", 3, 3, 1.0, 0.0, 1.0, False)
        sh = shipment_for(header, AS_OF)
        assert sh is not None
        age = (AS_OF - sh.delivered_on).days if sh.delivered_on else None
        ok = {
            "recent": sh.status == "delivered" and age is not None and age <= 14,
            "old": sh.status == "delivered" and age is not None and age > 30,
            "late": sh.status == "delivered_late",
            "lost": sh.status == "lost",
            "transit": sh.status == "in_transit" and sh.estimated_delivery > AS_OF,
            "returned": sh.status == "returned_to_sender",
        }[role]
        if ok:
            return str(n)
    raise AssertionError(f"no invoice number found for {role}")


PRODUCTS = [
    ("23355", "HOT WATER BOTTLE KEEP CALM", 8, 4.95),
    ("22470", "HEART OF WICKER LARGE", 12, 2.95),
    ("21481", "FAWN BLUE HOT WATER BOTTLE", 4, 3.75),
    ("22423", "REGENCY CAKESTAND 3 TIER", 6, 12.75),
]


@pytest.fixture(scope="session")
def fixture_orders(tmp_path_factory: pytest.TempPathFactory) -> Fixture:
    roles = {
        "recent": datetime(2011, 12, 1, 10, 0),
        "old": datetime(2011, 8, 1, 10, 0),
        "late": datetime(2011, 11, 10, 10, 0),
        "lost": datetime(2011, 10, 3, 10, 0),
        "transit": datetime(2011, 12, 9, 16, 0),
        "returned": datetime(2011, 10, 20, 10, 0),
    }
    invoices: dict[str, str] = {}
    rows = []
    start = 700000
    for role, when in roles.items():
        number = _find(role, when, start)
        start = int(number) + 1
        invoices[role] = number
        for code, desc, qty, price in PRODUCTS:
            rows.append((number, code, desc, qty, when, price, CUSTOMER, "United Kingdom"))
        if role == "late":
            rows.append((number, "POST", "POSTAGE", 1, when, 4.95, CUSTOMER, "United Kingdom"))
    invoices["credit"] = f"C{start + 5}"
    rows.append(
        (
            invoices["credit"],
            "23355",
            "HOT WATER BOTTLE KEEP CALM",
            -2,
            datetime(2011, 12, 2, 9, 0),
            4.95,
            CUSTOMER,
            "United Kingdom",
        )
    )
    invoices["other"] = str(start + 10)
    rows.append(
        (
            invoices["other"],
            "22423",
            "REGENCY CAKESTAND 3 TIER",
            4,
            datetime(2011, 12, 1, 9, 0),
            12.75,
            OTHER,
            "France",
        )
    )
    df = pd.DataFrame(
        rows,
        columns=[
            "invoice",
            "stock_code",
            "description",
            "quantity",
            "invoice_date",
            "price",
            "customer_id",
            "country",
        ],
    )
    df["invoice_date"] = pd.to_datetime(df["invoice_date"]).astype("datetime64[s]")
    canonical = tmp_path_factory.mktemp("canonical")
    df.to_parquet(canonical / "online-retail-ii.parquet", index=False)
    out = tmp_path_factory.mktemp("support")
    build_orders(canonical, out)
    return Fixture(OrderStore(out / "orders.duckdb"), invoices)


def keyword_search() -> Callable[[str, int], list[Hit]]:
    """An in-memory stand-in for the PostgreSQL search: rank chunks by shared words."""
    chunks = chunk_text(POLICY_TEXT, max_words=90, overlap=0)

    def words(text: str) -> set[str]:
        return {w[:5] for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3}

    def run(query: str, k: int) -> list[Hit]:
        q = words(query)
        scored = sorted(
            ((len(q & words(c.heading + " " + c.text)), c) for c in chunks),
            key=lambda x: (-x[0], x[1].ordinal),
        )
        return [
            Hit(c.ordinal + 1, 1, "policy", "Customer service policy", "synthetic", None, True,
                c.heading, c.ordinal, c.start, c.end, c.text, float(score), c.text[:120], [])
            for score, c in scored[:k] if score > 0
        ]  # fmt: skip

    return run


@pytest.fixture
def runtime(fixture_orders: Fixture) -> AgentRuntime:
    return AgentRuntime(
        store=fixture_orders.store,
        policy_search=keyword_search(),
        chain_factory=scripted_chain,
        as_of=AS_OF,
        auto_approve_limit=50.0,
    )
