"""Refund rules, simulated shipments and the scripted agent's reading of messages."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime

import pytest

from reluai_support.orders import InvoiceHeader
from reluai_support.refunds import ItemRequest, calculate_refund
from reluai_support.scripted import intent_of, invoice_numbers, match_items
from reluai_support.shipments import shipment_for

from .conftest import AS_OF, Fixture


def decide(f: Fixture, role: str, reason: str, items: list[ItemRequest] | None = None):  # type: ignore[no-untyped-def]
    invoice = f.store.invoice(f.invoices[role])
    assert invoice is not None
    return calculate_refund(
        invoice,
        shipment_for(invoice.header, AS_OF),
        reason,  # type: ignore[arg-type]
        items,
        as_of=AS_OF,
        auto_approve_limit=50.0,
    )


# ---------------------------------------------------------------- shipments
def _header(n: int, when: datetime, country: str = "United Kingdom") -> InvoiceHeader:
    return InvoiceHeader(str(n), when, 1, country, 3, 3, 10.0, 0.0, 10.0, False)


def test_shipments_are_deterministic_and_labelled() -> None:
    h = _header(581004, datetime(2011, 12, 8, 12))
    a, b = shipment_for(h, AS_OF), shipment_for(h, AS_OF)
    assert a == b
    assert a is not None and a.synthetic
    assert a.tracking_number.startswith("DEMO-")
    assert all(e.at.date() <= AS_OF for e in a.events)


def test_outcome_mix_is_as_documented() -> None:
    when = datetime(2011, 9, 1, 10)
    counts = Counter(shipment_for(_header(n, when), AS_OF).status for n in range(500000, 510000))  # type: ignore[union-attr]
    share = {k: v / 10000 for k, v in counts.items()}
    assert 0.83 < share["delivered"] < 0.89
    assert 0.06 < share["delivered_late"] < 0.10
    assert 0.03 < share["lost"] < 0.05
    assert 0.01 < share["returned_to_sender"] < 0.03


def test_credit_notes_have_no_shipment() -> None:
    h = InvoiceHeader("C1", datetime(2011, 12, 1), 1, "United Kingdom", 1, 1, -5, 0, -5, True)
    assert shipment_for(h, AS_OF) is None


def test_status_depends_on_the_desk_date() -> None:
    h = _header(581004, datetime(2011, 12, 8, 12))
    early = shipment_for(h, date(2011, 12, 9))
    later = shipment_for(h, date(2012, 1, 31))
    assert early is not None and later is not None
    assert early.status == "in_transit"
    assert later.status != "in_transit"
    assert len(later.events) >= len(early.events)


# ---------------------------------------------------------------- refund rules
def test_damage_within_window_refunds_the_quantity(fixture_orders: Fixture) -> None:
    d = decide(fixture_orders, "recent", "damaged", [ItemRequest("21481", 2)])
    assert d.eligible
    assert d.amount == 7.50
    assert d.approval == "agent"
    assert d.lines[0].return_needed is True  # the line cost £15.00, not under £15
    whole = decide(fixture_orders, "recent", "damaged", [ItemRequest("22423")])
    assert whole.amount == 76.50
    assert whole.approval == "supervisor"
    assert whole.lines[0].return_needed is True


@pytest.mark.parametrize(
    ("items", "message"),
    [
        ([ItemRequest("99999", 1)], "not a product on this invoice"),
        ([ItemRequest("21481", 5)], "cannot be refunded"),
    ],
)
def test_items_are_checked_against_the_invoice(
    fixture_orders: Fixture, items: list[ItemRequest], message: str
) -> None:
    d = decide(fixture_orders, "recent", "damaged", items)
    assert not d.eligible
    assert message in d.explanation


def test_damage_after_the_window(fixture_orders: Fixture) -> None:
    d = decide(fixture_orders, "old", "damaged", [ItemRequest("21481", 1)])
    assert not d.eligible
    assert "14 days" in d.explanation


def test_returns_are_refunded_on_receipt(fixture_orders: Fixture) -> None:
    d = decide(fixture_orders, "recent", "return_unused", [ItemRequest("23355")])
    assert d.eligible and d.refund_on_return
    assert d.approval == "none"
    assert d.amount == 39.60
    assert not decide(fixture_orders, "old", "return_unused").eligible


def test_late_delivery_refunds_postage(fixture_orders: Fixture) -> None:
    d = decide(fixture_orders, "late", "late_delivery")
    assert d.eligible and d.amount == 4.95
    assert not decide(fixture_orders, "recent", "late_delivery").eligible


def test_lost_parcel_refunds_the_goods(fixture_orders: Fixture) -> None:
    d = decide(fixture_orders, "lost", "lost_parcel")
    assert d.eligible
    assert d.amount == 166.50
    assert d.approval == "supervisor"
    assert not decide(fixture_orders, "transit", "lost_parcel").eligible


def test_nothing_before_delivery_and_nothing_on_credit_notes(fixture_orders: Fixture) -> None:
    assert not decide(fixture_orders, "transit", "damaged").eligible
    credit = decide(fixture_orders, "credit", "damaged")
    assert not credit.eligible
    assert "credit note" in credit.explanation


def test_no_shipping_charge_means_a_capped_credit() -> None:
    from reluai_support.orders import Invoice, Line
    from reluai_support.shipments import Shipment

    late = Shipment(
        "1", "DEMO-1", "Tracked UK 48", "delivered_late",
        date(2011, 11, 2), date(2011, 11, 4), date(2011, 11, 12), 8,
    )  # fmt: skip
    lines = [Line(1, "X", "THING", 100, 9.99, 999.0, "product")]

    def credit(goods: float) -> float:
        header = InvoiceHeader(
            "1",
            datetime(2011, 11, 1),
            1,
            "United Kingdom",
            1,
            100,
            goods,
            0.0,
            goods,
            False,
        )
        d = calculate_refund(
            Invoice(header, lines), late, "late_delivery", None, as_of=AS_OF, auto_approve_limit=50
        )
        return d.amount

    assert credit(999.0) == 10.0  # 5% capped at £10
    assert credit(60.0) == 3.0


# ---------------------------------------------------------------- reading messages
@pytest.mark.parametrize(
    ("text", "intent"),
    [
        ("The mugs arrived smashed", "damaged"),
        ("Two of the bottles are leaking", "damaged"),
        ("The candles weren't in the box", "missing"),
        ("I never received my order", "not_received"),
        ("It took ages to arrive", "late"),
        ("I'd like to return the chocolate hot water bottles", "return"),  # not "late"
        ("Please cancel order 581186", "cancel"),
        ("What was the total of invoice 574755?", "info"),
        ("Refund me now", "refund"),
        ("Hello there", None),
    ],
)
def test_intents(text: str, intent: str | None) -> None:
    assert intent_of(text) == intent


def test_invoice_numbers() -> None:
    assert invoice_numbers("orders 578058 and c568232, not 12345 or 1234567") == [
        "578058",
        "C568232",
    ]


PRODUCTS = [
    {"stock_code": "23355", "description": "HOT WATER BOTTLE KEEP CALM", "quantity": 8},
    {"stock_code": "22112", "description": "CHOCOLATE HOT WATER BOTTLE", "quantity": 9},
    {"stock_code": "22470", "description": "HEART OF WICKER LARGE", "quantity": 12},
    {"stock_code": "22469", "description": "HEART OF WICKER SMALL", "quantity": 12},
]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2 of the keep calm hot water bottles cracked", [("23355", 2)]),
        ("all the chocolate hot water bottles leak", [("22112", None)]),
        ("the large wicker hearts were broken, 4 of them", [("22470", 4)]),
        (
            "the keep calm bottles leak and 3 small wicker hearts broke too",
            [("23355", None), ("22469", 3)],
        ),
        ("the wicker hearts were broken", []),  # ambiguous: large or small
        ("invoice 578059: twenty keep calm bottles", [("23355", 8)]),  # capped at the line
    ],
)
def test_product_matching(text: str, expected: list[tuple[str, int | None]]) -> None:
    got = [(i["stock_code"], i["quantity"]) for i in match_items(text, PRODUCTS)]
    assert got == expected
