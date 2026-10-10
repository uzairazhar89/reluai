"""The agent's tools: validated arguments in, plain JSON out, scoped to one customer.

Every tool is ordinary, tested Python. The model only proposes calls; arguments are
validated by Pydantic before anything runs (see ``reluai_inference.tools``). Tools that
"act" (refunds, tickets, replies) create simulated records on the conversation; nothing
leaves the system. Domain refusals (another customer's invoice, an amount the rules did
not produce) are raised as ``LookupError``/``ValueError`` and returned to the model as data.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from reluai_inference.tools import ToolRegistry
from reluai_retrieval.search import Hit
from reluai_support.orders import Invoice, OrderStore
from reluai_support.refunds import ItemRequest, Reason, calculate_refund
from reluai_support.shipments import shipment_for
from reluai_support.state import ApprovalRequest, Refund, SessionState, Source, Ticket, now

InvoiceNo = Field(pattern=r"^C?\d{6}$", description="Invoice number, e.g. 578058 or C568232")
PolicySearch = Callable[[str, int], list[Hit]]
MAX_LINES_SHOWN = 40


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetInvoiceArgs(_Args):
    invoice_no: str = InvoiceNo


class ListInvoicesArgs(_Args):
    limit: int = Field(default=5, ge=1, le=20)


class ShipmentArgs(_Args):
    invoice_no: str = InvoiceNo


class SearchPolicyArgs(_Args):
    query: str = Field(min_length=3, max_length=200, description="What to look up")


class RefundItem(_Args):
    stock_code: str = Field(min_length=1, max_length=20)
    quantity: int | None = Field(default=None, ge=1, description="Omit for the whole line")


class CalculateRefundArgs(_Args):
    invoice_no: str = InvoiceNo
    reason: Reason
    items: list[RefundItem] | None = Field(
        default=None,
        max_length=20,
        description="Affected products (stock code and quantity); omit for the whole order",
    )


class RequestApprovalArgs(_Args):
    invoice_no: str = InvoiceNo
    reason: Reason
    amount: float = Field(gt=0, description="Exactly the amount calculate_refund returned")


TicketCategory = Literal[
    "lost_parcel_investigation",
    "return_request",
    "goodwill_review",
    "vat_invoice",
    "address_check",
    "complaint",
    "other",
]


class CreateTicketArgs(_Args):
    category: TicketCategory
    priority: Literal["low", "normal", "high"] = "normal"
    invoice_no: str | None = Field(default=None, pattern=r"^C?\d{6}$")
    summary: str = Field(min_length=5, max_length=300)


class DraftReplyArgs(_Args):
    message: str = Field(min_length=5, max_length=1500, description="Plain text to the customer")
    citations: list[int] = Field(
        default_factory=list, max_length=10, description="Policy passage numbers cited as [n]"
    )


@dataclass
class ToolContext:
    session: SessionState
    store: OrderStore
    policy_search: PolicySearch
    as_of: date
    auto_approve_limit: float
    customer_country: str = ""

    # ------------------------------------------------------------------ helpers
    def _own_invoice(self, invoice_no: str) -> Invoice:
        invoice = self.store.invoice(invoice_no.upper())
        if invoice is None or invoice.header.customer_id != self.session.customer_id:
            # Same answer whether the invoice exists for someone else or not at all.
            raise LookupError(f"No invoice {invoice_no} on this customer's account.")
        return invoice

    @staticmethod
    def _money(x: float) -> float:
        return round(x, 2)

    # ------------------------------------------------------------------ read tools
    def get_invoice(self, a: GetInvoiceArgs) -> dict[str, Any]:
        inv = self._own_invoice(a.invoice_no)
        h = inv.header
        products = [ln for ln in inv.lines if ln.kind == "product"]
        return {
            "invoice_no": h.invoice_no,
            "date": h.invoiced_at.strftime("%Y-%m-%d %H:%M"),
            "is_credit_note": h.is_credit_note,
            "goods_total_gbp": self._money(h.goods_total),
            "shipping_gbp": self._money(h.shipping_total),
            "total_gbp": self._money(h.total),
            "products": [
                {
                    "stock_code": ln.stock_code,
                    "description": ln.description,
                    "quantity": ln.quantity,
                    "unit_price_gbp": ln.unit_price,
                    "line_total_gbp": ln.line_total,
                }
                for ln in products[:MAX_LINES_SHOWN]
            ],
            "more_products": max(0, len(products) - MAX_LINES_SHOWN),
            "other_lines": [
                {"description": ln.description, "amount_gbp": ln.line_total}
                for ln in inv.lines
                if ln.kind != "product"
            ],
        }

    def list_customer_invoices(self, a: ListInvoicesArgs) -> dict[str, Any]:
        headers = self.store.customer_invoices(self.session.customer_id, limit=a.limit)
        return {
            "customer_id": self.session.customer_id,
            "invoices": [
                {
                    "invoice_no": h.invoice_no,
                    "date": h.invoiced_at.strftime("%Y-%m-%d"),
                    "products": h.lines,
                    "total_gbp": self._money(h.total),
                    "is_credit_note": h.is_credit_note,
                }
                for h in headers
            ],
        }

    def get_shipment_status(self, a: ShipmentArgs) -> dict[str, Any]:
        inv = self._own_invoice(a.invoice_no)
        sh = shipment_for(inv.header, self.as_of)
        if sh is None:
            return {
                "invoice_no": inv.header.invoice_no,
                "shipment": None,
                "note": "Credit notes have no shipment.",
            }
        return {
            "invoice_no": sh.invoice_no,
            "synthetic": True,
            "tracking_number": sh.tracking_number,
            "service": sh.service,
            "status": sh.status,
            "dispatched_on": sh.dispatched_on.isoformat(),
            "estimated_delivery": sh.estimated_delivery.isoformat(),
            "delivered_on": sh.delivered_on.isoformat() if sh.delivered_on else None,
            "days_late": sh.days_late,
            "events": [
                {"at": e.at.strftime("%Y-%m-%d %H:%M"), "event": e.description} for e in sh.events
            ],
        }

    def search_policy(self, a: SearchPolicyArgs) -> dict[str, Any]:
        hits = self.policy_search(a.query, 3)
        results = []
        for h in hits:
            existing = next(
                (i for i, s in enumerate(self.session.sources) if s.chunk_id == h.chunk_id), None
            )
            if existing is None:
                self.session.sources.append(
                    Source(chunk_id=h.chunk_id, heading=h.heading, text=h.text, quote=h.snippet)
                )
                existing = len(self.session.sources) - 1
            results.append({"citation": existing + 1, "section": h.heading, "text": h.text})
        return {
            "passages": results,
            "note": "Cite passages as [n]. The policy was written for this demo (synthetic).",
        }

    # ------------------------------------------------------------------ action tools
    def calculate_refund(self, a: CalculateRefundArgs) -> dict[str, Any]:
        inv = self._own_invoice(a.invoice_no)
        decision = calculate_refund(
            inv,
            shipment_for(inv.header, self.as_of),
            a.reason,
            [ItemRequest(i.stock_code, i.quantity) for i in a.items] if a.items else None,
            as_of=self.as_of,
            auto_approve_limit=self.auto_approve_limit,
        )
        result = {
            "invoice_no": decision.invoice_no,
            "reason": decision.reason,
            "eligible": decision.eligible,
            "amount_gbp": decision.amount,
            "approval_needed": {
                "agent": f"none: within the £{self.auto_approve_limit:g} agent limit",
                "supervisor": "supervisor approval",
                "none": "not applicable",
            }[decision.approval],
            "refund_on_return": decision.refund_on_return,
            "policy_section": decision.policy_section,
            "explanation": decision.explanation,
            "lines": [
                {
                    "stock_code": ln.stock_code,
                    "description": ln.description,
                    "quantity": ln.quantity,
                    "amount_gbp": ln.amount,
                    "return_needed": ln.return_needed,
                }
                for ln in decision.lines
            ],
        }
        self.session.calculations[f"{decision.invoice_no}:{decision.reason}"] = {
            "eligible": decision.eligible,
            "amount": decision.amount,
            "approval": decision.approval,
            "refund_on_return": decision.refund_on_return,
        }
        return result

    def request_approval(self, a: RequestApprovalArgs) -> dict[str, Any]:
        invoice_no = self._own_invoice(a.invoice_no).header.invoice_no
        calc = self.session.calculations.get(f"{invoice_no}:{a.reason}")
        if calc is None:
            raise ValueError("Call calculate_refund for this invoice and reason first.")
        if not calc["eligible"]:
            raise ValueError("calculate_refund found no eligible refund for this reason.")
        if calc["refund_on_return"]:
            raise ValueError(
                "Returns are refunded when the items arrive: create a return_request ticket."
            )
        if abs(float(calc["amount"]) - a.amount) > 0.005:
            raise ValueError(
                f"The amount must be exactly £{calc['amount']:.2f}, as calculated by the rules."
            )
        for existing in self.session.approvals:
            if existing.invoice_no == invoice_no and existing.reason == a.reason:
                return {
                    "status": existing.status,
                    "approval_id": existing.id,
                    "note": "This refund was already requested.",
                }
        req = ApprovalRequest(
            id=f"A-{secrets.token_hex(3).upper()}",
            invoice_no=invoice_no,
            reason=a.reason,
            amount=round(a.amount, 2),
            status="pending",
        )
        self.session.approvals.append(req)
        if calc["approval"] == "agent":
            req.status, req.decided_by, req.decided_at = "approved", "agent", now()
            self.session.refunds.append(
                Refund(
                    invoice_no=invoice_no, reason=a.reason, amount=req.amount, approved_by="agent"
                )
            )
            return {
                "status": "approved",
                "approval_id": req.id,
                "note": f"Within the £{self.auto_approve_limit:g} agent limit: refund recorded "
                "(simulated; paid within 5 working days).",
            }
        return {
            "status": "pending_supervisor",
            "approval_id": req.id,
            "note": "A supervisor must approve this refund. Tell the customer it is pending.",
        }

    def create_ticket(self, a: CreateTicketArgs) -> dict[str, Any]:
        invoice_no = self._own_invoice(a.invoice_no).header.invoice_no if a.invoice_no else None
        for t in self.session.tickets:
            if t.category == a.category and t.invoice_no == invoice_no:
                return {"ticket_id": t.id, "note": "A ticket for this already exists."}
        ticket = Ticket(
            id=f"T-{secrets.token_hex(3).upper()}",
            category=a.category,
            priority=a.priority,
            invoice_no=invoice_no,
            summary=a.summary,
        )
        self.session.tickets.append(ticket)
        return {"ticket_id": ticket.id, "category": ticket.category, "status": "open (simulated)"}

    def draft_reply(self, a: DraftReplyArgs) -> dict[str, Any]:
        unknown = [n for n in a.citations if not 1 <= n <= len(self.session.sources)]
        if unknown:
            raise ValueError(
                f"Citations {unknown} do not match a retrieved passage "
                f"(1 to {len(self.session.sources)})."
            )
        self.session.reply = a.message.strip()
        return {"drafted": True, "note": "Saved as a draft. Nothing is sent automatically."}

    # ------------------------------------------------------------------ registry
    def registry(self) -> ToolRegistry:
        r = ToolRegistry()
        r.register(
            "get_invoice",
            "Invoice header, products (stock code, description, quantity, price) and totals.",
            GetInvoiceArgs,
            self.get_invoice,
        )
        r.register(
            "list_customer_invoices",
            "The customer's most recent invoices, newest first.",
            ListInvoicesArgs,
            self.list_customer_invoices,
        )
        r.register(
            "get_shipment_status",
            "Tracking for an invoice: status, estimated and actual delivery, events.",
            ShipmentArgs,
            self.get_shipment_status,
        )
        r.register(
            "search_policy",
            "Search the customer service policy. Returns numbered passages to cite as [n].",
            SearchPolicyArgs,
            self.search_policy,
        )
        r.register(
            "calculate_refund",
            "Apply the refund rules for one reason on one invoice. The only source of refund "
            "amounts.",
            CalculateRefundArgs,
            self.calculate_refund,
        )
        r.register(
            "request_approval",
            "Issue a refund calculated by calculate_refund. Within the agent limit it is "
            "recorded at once; above it, it waits for a supervisor.",
            RequestApprovalArgs,
            self.request_approval,
        )
        r.register(
            "create_ticket",
            "Open a ticket for a person to follow up (investigation, return, VAT invoice, "
            "goodwill review, address check, complaint).",
            CreateTicketArgs,
            self.create_ticket,
        )
        r.register(
            "draft_reply",
            "Save the reply to the customer and end this turn. Nothing is sent.",
            DraftReplyArgs,
            self.draft_reply,
        )
        return r
