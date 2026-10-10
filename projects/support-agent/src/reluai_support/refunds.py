"""Refund rules: the policy in code, so amounts never come from a model.

``calculate_refund`` decides eligibility and the amount for one reason on one invoice. The
agent may only request approval for an amount this function produced (``approvals`` checks
it), so a persuasive message or a confused model cannot raise a refund.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

from reluai_support.orders import Invoice, Line
from reluai_support.shipments import LOST_AFTER_DAYS, Shipment

Reason = Literal["damaged", "missing_items", "late_delivery", "lost_parcel", "return_unused"]
Approval = Literal["agent", "supervisor", "none"]

DAMAGE_WINDOW_DAYS = 14
RETURN_WINDOW_DAYS = 30
NO_RETURN_UNDER_GBP = 15.0
LATE_CREDIT_SHARE = 0.05
LATE_CREDIT_CAP_GBP = 10.0

SECTION = {
    "damaged": "Refunds › Damaged or faulty items",
    "missing_items": "Refunds › Missing items",
    "late_delivery": "Delivery › Late deliveries",
    "lost_parcel": "Delivery › Lost parcels",
    "return_unused": "Returns",
}


@dataclass(frozen=True, slots=True)
class ItemRequest:
    stock_code: str
    quantity: int | None = None  # None: the whole line


@dataclass(frozen=True, slots=True)
class RefundLine:
    stock_code: str
    description: str
    quantity: int
    unit_price: float
    amount: float
    return_needed: bool


@dataclass(frozen=True, slots=True)
class RefundDecision:
    invoice_no: str
    reason: Reason
    eligible: bool
    amount: float
    approval: Approval
    refund_on_return: bool
    policy_section: str
    explanation: str
    lines: list[RefundLine] = field(default_factory=list)


def _round(x: float) -> float:
    return round(x + 1e-9, 2)


def _day(d: date) -> str:
    return f"{d.day} {d:%B %Y}"


def _no(invoice: Invoice, reason: Reason, why: str) -> RefundDecision:
    return RefundDecision(
        invoice_no=invoice.header.invoice_no,
        reason=reason,
        eligible=False,
        amount=0.0,
        approval="none",
        refund_on_return=False,
        policy_section=SECTION[reason],
        explanation=why,
    )


def _select_lines(
    invoice: Invoice, items: list[ItemRequest] | None
) -> tuple[list[RefundLine], str | None]:
    products = [ln for ln in invoice.lines if ln.kind == "product" and ln.quantity > 0]
    chosen: list[tuple[Line, int]] = []
    if not items:
        chosen = [(ln, ln.quantity) for ln in products]
    else:
        by_code: dict[str, Line] = {}
        for ln in products:
            by_code.setdefault(ln.stock_code.upper(), ln)
        for item in items:
            line = by_code.get(item.stock_code.strip().upper())
            if line is None:
                return [], f"Stock code {item.stock_code} is not a product on this invoice."
            qty = line.quantity if item.quantity is None else item.quantity
            if qty <= 0:
                return [], "Quantities must be at least 1."
            if qty > line.quantity:
                return [], (
                    f"The invoice has {line.quantity} of {item.stock_code}; "
                    f"{qty} cannot be refunded."
                )
            chosen.append((line, qty))
    out = [
        RefundLine(
            stock_code=ln.stock_code,
            description=ln.description,
            quantity=qty,
            unit_price=ln.unit_price,
            amount=_round(ln.unit_price * qty),
            return_needed=ln.unit_price * ln.quantity >= NO_RETURN_UNDER_GBP,
        )
        for ln, qty in chosen
    ]
    return out, None


def calculate_refund(  # noqa: PLR0911, PLR0912
    invoice: Invoice,
    shipment: Shipment | None,
    reason: Reason,
    items: list[ItemRequest] | None,
    *,
    as_of: date,
    auto_approve_limit: float,
) -> RefundDecision:
    h = invoice.header
    if h.is_credit_note:
        return _no(
            invoice,
            reason,
            f"{h.invoice_no} is a credit note: it records a cancellation or refund that has "
            "already been processed, so no further refund is due.",
        )
    if shipment is None:
        return _no(invoice, reason, "There is no shipment for this invoice.")

    delivered = shipment.delivered_on
    if reason in {"damaged", "missing_items", "return_unused"}:
        if delivered is None:
            return _no(
                invoice,
                reason,
                "The parcel has not been delivered yet (tracking status: "
                f"{shipment.status.replace('_', ' ')}), so nothing can be reported as damaged, "
                "missing or returned yet.",
            )
        window = RETURN_WINDOW_DAYS if reason == "return_unused" else DAMAGE_WINDOW_DAYS
        age = (as_of - delivered).days
        if age > window:
            return _no(
                invoice,
                reason,
                f"The parcel was delivered on {_day(delivered)}, {age} days ago, and the policy "
                f"accepts {'returns' if reason == 'return_unused' else 'reports'} for {window} "
                "days after delivery.",
            )
        lines, problem = _select_lines(invoice, items)
        if problem:
            return _no(invoice, reason, problem)
        amount = _round(sum(ln.amount for ln in lines))
        if reason == "return_unused":
            return RefundDecision(
                invoice_no=h.invoice_no,
                reason=reason,
                eligible=True,
                amount=amount,
                approval="none",
                refund_on_return=True,
                policy_section=SECTION[reason],
                explanation=(
                    f"Delivered {age} days ago, within the {window}-day return window. The "
                    "refund is issued when the items arrive back; create a return request."
                ),
                lines=lines,
            )
        explanation = f"Delivered {age} days ago, within the {window}-day reporting window."
    elif reason == "late_delivery":
        if delivered is None or shipment.status != "delivered_late":
            return _no(
                invoice,
                reason,
                "The delivery was not late: "
                + (
                    f"it arrived on {_day(delivered)}, "
                    if delivered
                    else f"its status is {shipment.status.replace('_', ' ')}, "
                )
                + f"and the estimated date was {_day(shipment.estimated_delivery)}. A delivery "
                "counts as late more than 3 days after the estimate.",
            )
        if h.shipping_total > 0:
            amount = _round(h.shipping_total)
            explanation = f"Delivered {shipment.days_late} days late: shipping charge refunded."
        else:
            amount = _round(min(h.goods_total * LATE_CREDIT_SHARE, LATE_CREDIT_CAP_GBP))
            explanation = (
                f"Delivered {shipment.days_late} days late and the invoice has no shipping "
                "charge: 5% of the goods, up to £10."
            )
        lines = []
    else:  # lost_parcel
        if shipment.status != "lost":
            return _no(
                invoice,
                reason,
                f"The parcel is not lost: its tracking status is "
                f"{shipment.status.replace('_', ' ')}. A parcel counts as lost when it has not "
                f"arrived {LOST_AFTER_DAYS} days after the estimated delivery date "
                f"({_day(shipment.estimated_delivery)}).",
            )
        lines, _ = _select_lines(invoice, None)
        amount = _round(sum(ln.amount for ln in lines))
        explanation = (
            f"No delivery {shipment.days_late} days after the estimated date: refund of the "
            "goods and a carrier investigation."
        )

    amount = min(amount, _round(h.goods_total + h.shipping_total))
    if amount <= 0:
        return _no(invoice, reason, "Nothing on this invoice can be refunded for that reason.")
    return RefundDecision(
        invoice_no=h.invoice_no,
        reason=reason,
        eligible=True,
        amount=amount,
        approval="agent" if amount <= auto_approve_limit else "supervisor",
        refund_on_return=False,
        policy_section=SECTION[reason],
        explanation=explanation,
        lines=lines,
    )
