"""Synthetic shipments, derived deterministically from real invoices.

Real retailers' tracking data is not public, so each invoice gets a simulated shipment
computed from its number and date: the same invoice always has the same shipment. Carrier
services have generic names (no real carrier is named next to a "delayed" or "lost"
status). Every result carries ``synthetic: true``.

Outcomes, by a hash of the invoice number: about 86% delivered on time, 8% delivered late,
4% lost (no delivery scan, investigation needed) and 2% returned to sender.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Literal

from reluai_support.orders import InvoiceHeader

Status = Literal["in_transit", "delivered", "delivered_late", "lost", "returned_to_sender"]

UK = {"United Kingdom", "Channel Islands"}
EUROPE = {
    "Austria", "Belgium", "Cyprus", "Czech Republic", "Denmark", "EIRE", "European Community",
    "Finland", "France", "Germany", "Greece", "Iceland", "Italy", "Lithuania", "Malta",
    "Netherlands", "Norway", "Poland", "Portugal", "Spain", "Sweden", "Switzerland",
}  # fmt: skip
LATE_AFTER_DAYS = 3  # delivered more than this many days after the estimate counts as late
LOST_AFTER_DAYS = 10  # no delivery this many days after the estimate: treated as lost


@dataclass(frozen=True, slots=True)
class Event:
    at: datetime
    code: str
    description: str


@dataclass(frozen=True, slots=True)
class Shipment:
    invoice_no: str
    tracking_number: str
    service: str
    status: Status
    dispatched_on: date
    estimated_delivery: date
    delivered_on: date | None
    days_late: int
    events: list[Event] = field(default_factory=list)
    synthetic: bool = True


def _hash(invoice_no: str) -> int:
    return int(hashlib.sha256(f"shipment:{invoice_no}".encode()).hexdigest()[:12], 16)


def _working_day(d: date) -> date:
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def _at(d: date, hour: int, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute)  # noqa: DTZ001 - local warehouse time


def shipment_for(invoice: InvoiceHeader, as_of: date) -> Shipment | None:  # noqa: PLR0912
    """The simulated shipment of an invoice as known on ``as_of``; none for credit notes."""
    if invoice.is_credit_note:
        return None
    h = _hash(invoice.invoice_no)
    ordered = invoice.invoiced_at
    dispatched = _working_day(ordered.date() + timedelta(days=1 if ordered.hour < 15 else 2))
    if invoice.country in UK:
        service, transit = "Tracked UK 48", 2 + h % 2
    elif invoice.country in EUROPE:
        service, transit = "Tracked Europe", 3 + h % 4
    else:
        service, transit = "International Tracked", 6 + h % 6
    estimated = dispatched + timedelta(days=transit)
    roll = (h >> 8) % 100
    if roll < 4:
        outcome: Status = "lost"
        delivered: date | None = None
    elif roll < 6:
        outcome, delivered = "returned_to_sender", None
    elif roll < 14:
        outcome = "delivered_late"
        delivered = estimated + timedelta(days=LATE_AFTER_DAYS + 1 + (h >> 16) % 9)
    else:
        outcome, delivered = "delivered", estimated - timedelta(days=(h >> 16) % 2)

    events = [
        Event(_at(ordered.date(), ordered.hour, ordered.minute), "ordered", "Order received"),
        Event(_at(dispatched, 17), "dispatched", "Parcel handed to the carrier"),
        Event(_at(dispatched + timedelta(days=1), 6, 30), "in_transit", "In transit"),
    ]
    status: Status = "in_transit"
    days_late = 0
    if outcome == "lost":
        events.append(
            Event(_at(dispatched + timedelta(days=2), 9), "hub", "Arrived at the sorting hub")
        )
        if as_of > estimated + timedelta(days=LOST_AFTER_DAYS):
            status = "lost"
            days_late = (as_of - estimated).days
    elif outcome == "returned_to_sender":
        returned = estimated + timedelta(days=6)
        events.append(
            Event(_at(estimated, 11), "failed_delivery", "Delivery attempted, address not found")
        )
        if as_of >= returned:
            status = "returned_to_sender"
            events.append(Event(_at(returned, 14), "returned", "Returned to the warehouse"))
    elif delivered is not None and as_of >= delivered:
        status = outcome
        days_late = max(0, (delivered - estimated).days)
        events.append(Event(_at(delivered, 10 + h % 7), "delivered", "Delivered"))
    events = [e for e in events if e.at.date() <= as_of]
    return Shipment(
        invoice_no=invoice.invoice_no,
        tracking_number=f"DEMO-{h:012X}"[:17],
        service=service,
        status=status,
        dispatched_on=dispatched,
        estimated_delivery=estimated,
        delivered_on=delivered if status in {"delivered", "delivered_late"} else None,
        days_late=days_late,
        events=events,
    )
