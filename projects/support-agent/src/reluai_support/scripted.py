"""The scripted agent: a rule-based stand-in for a model, used when none is available.

It plugs into the provider chain as the last provider, so it receives the same messages and
tools a model would and answers with tool calls. It reads the customer's words with
keywords and product-name matching, then follows a fixed procedure: look up the invoice
(and shipment), search the policy, calculate, request approval or open a ticket, and draft
a reply with citations. It is deliberately simple and is labelled "Scripted" wherever it
answers; it shows that the tools, rules and approval flow work without any model, and it
is the baseline the models are compared with.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from reluai_inference.types import ChatRequest, ChatResponse, Message, ToolCall

SUPERVISOR_PREFIX = "[Supervisor]"
_INVOICE = re.compile(r"\b([Cc]?\d{6})\b")
_WORD = re.compile(r"[a-z]+")
_NUMBER = re.compile(r"(?<![£\d.])\b(\d{1,4})\b(?![\d.%])")
_CLAUSE = re.compile(r",|;|\band\b|\.\s|\btoo\b|\balso\b|—|\s-\s")
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "dozen": 12, "twenty": 20,
    "both": 2, "pair": 2, "couple": 2,
}  # fmt: skip
ALL_WORDS = {"all", "every", "none", "whole", "entire"}
STOP = {
    "the", "and", "for", "from", "with", "were", "was", "all", "them", "they", "their", "this",
    "that", "these", "those", "order", "orders", "invoice", "arrived", "came", "have", "has",
    "had", "but", "not", "our", "your", "you", "can", "get", "please", "refund", "hi", "hello",
    "thanks", "thank", "would", "like", "want", "just", "box", "parcel", "package", "delivery",
    "item", "items", "one", "two", "three", "four", "five", "six", "ten", "twelve", "every",
    "single", "set", "sets", "pack", "packs", "too", "also", "some", "any", "none", "into",
    "out", "back", "send", "return", "unused", "never", "used", "are", "its", "it", "of",
    "on", "in", "a", "an", "my", "me", "we", "is", "be", "to", "did", "didn", "don", "doesn",
    "wasn", "weren", "work", "working", "broken", "damaged", "missing", "faulty", "cracked",
    "smashed", "chipped", "dented", "leak", "leaking", "leaks", "torn", "snapped", "crushed",
    "melted", "time", "first", "use", "changed", "mind", "both", "dozen", "half", "whole",
    "design", "assorted", "colour",
}  # fmt: skip

INTENTS: list[tuple[str, tuple[str, ...]]] = [
    (
        "damaged",
        (
            "damag",
            "broke",
            "crack",
            "smash",
            "chipped",
            "dent",
            "leak",
            "faulty",
            "defect",
            "not work",
            "doesn't work",
            "don't work",
            "dont work",
            "torn",
            "snapped",
            "crushed",
            "melted",
            "shatter",
            "scratch",
        ),
    ),
    (
        "missing",
        (
            "missing",
            "without the",
            "wasn't in",
            "weren't in",
            "not in the box",
            "left out",
            "didn't receive the",
            "did not receive the",
            "didn't get the",
        ),
    ),
    (
        "not_received",
        (
            "never received",
            "not received",
            "hasn't arrived",
            "has not arrived",
            "hasn't come",
            "never arrived",
            "didn't arrive",
            "did not arrive",
            "where is",
            "never turned up",
            "still hasn't",
            "still not",
            "not arrived",
            "lost",
        ),
    ),
    (
        "late",
        (
            "late",
            "took ages",
            "slow",
            "delayed",
            "should have come",
            "took too long",
            "took forever",
            "shipping back",
        ),
    ),
    (
        "return",
        (
            "return",
            "send back",
            "send them back",
            "changed my mind",
            "unused",
            "don't want",
            "no longer want",
        ),
    ),
    ("cancel", ("cancel",)),
    (
        "info",
        (
            "total",
            "how much",
            "copy of",
            "vat",
            "how many",
            "what did i order",
            "what was on",
            "receipt",
        ),
    ),
    ("refund", ("refund", "money back", "compensation", "reimburse")),
]
POLICY_QUERY = {
    "damaged": "damaged or faulty items refund",
    "missing": "missing items from a delivered parcel",
    "not_received": "lost parcels not delivered",
    "late": "late deliveries refund shipping",
    "return": "returns of unused items",
    "cancel": "cancellations and credit notes",
    "info": "invoices and VAT copies",
    "credit": "credit notes cancellations already processed",
    "refund": "how refunds work",
}


def _norm(word: str) -> str:
    for suffix in ("ies", "es", "s"):
        if word.endswith(suffix) and len(word) > len(suffix) + 2:
            return word[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return word


def _tokens(text: str) -> set[str]:
    return {_norm(w) for w in _WORD.findall(text.lower()) if len(w) >= 3 and w not in STOP}


def intent_of(text: str) -> str | None:
    """The first matching intent; keys match at the start of a word ("late" ≠ "chocolate")."""
    lowered = text.lower().replace("’", "'")
    for name, keys in INTENTS:
        if any(re.search(rf"\b{re.escape(k)}", lowered) for k in keys):
            return name
    return None


def invoice_numbers(text: str) -> list[str]:
    return [m.upper() for m in _INVOICE.findall(text)]


def _quantity(clause: str, invoice_nos: set[str]) -> int | None:
    lowered = clause.lower()
    if any(re.search(rf"\b{w}\b", lowered) for w in ALL_WORDS):
        return None
    for m in _NUMBER.finditer(lowered):
        if m.group(1) not in invoice_nos:
            return int(m.group(1))
    for word, n in NUMBER_WORDS.items():
        if re.search(rf"\b{word}\b", lowered):
            return n
    return None


def match_items(text: str, products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Products the customer names, with quantities: one best match per clause."""
    invoice_nos = set(invoice_numbers(text))
    clauses = [c for c in _CLAUSE.split(text) if c and c.strip()]
    chosen: dict[str, dict[str, Any]] = {}
    last: dict[str, Any] | None = None
    for clause in clauses:
        words = _tokens(clause)
        scored = []
        for p in products:
            overlap = len(words & _tokens(p["description"]))
            if overlap:
                scored.append((overlap, p))
        if not scored:
            # "..., 4 of them": a quantity on its own refers to the product just named.
            qty = _quantity(clause, invoice_nos)
            if (
                last is not None
                and qty is not None
                and chosen[last["stock_code"]]["quantity"] is None
            ):
                chosen[last["stock_code"]]["quantity"] = min(qty, int(last["quantity"]))
            continue
        best = max(s for s, _ in scored)
        top = [p for s, p in scored if s == best]
        if len(top) > 1:
            continue  # ambiguous clause: say nothing rather than guess
        product = top[0]
        qty = _quantity(clause, invoice_nos)
        if qty is not None:
            qty = min(qty, int(product["quantity"]))
        chosen[product["stock_code"]] = {"stock_code": product["stock_code"], "quantity": qty}
        last = product
    return list(chosen.values())


@dataclass
class _Call:
    name: str
    args: dict[str, Any]
    ok: bool
    result: Any
    error: str | None
    turn: int


@dataclass
class _View:
    """What the scripted agent can see: messages in, tool results by name."""

    customer_texts: list[str] = field(default_factory=list)
    latest_customer: str = ""
    supervisor: str | None = None
    calls: list[_Call] = field(default_factory=list)
    turn: int = 0
    sources: list[tuple[int, str]] = field(default_factory=list)  # (citation, section)

    def find(self, name: str, *, this_turn: bool = False, **args: Any) -> _Call | None:
        for c in reversed(self.calls):
            if c.name != name or (this_turn and c.turn != self.turn):
                continue
            if all(c.args.get(k) == v for k, v in args.items()):
                return c
        return None

    def cite(self, *sections: str) -> str:
        nums = [n for n, sec in self.sources if any(sec.startswith(s) for s in sections)]
        return f" [{nums[0]}]" if nums else ""

    def cite_numbers(self, *sections: str) -> list[int]:
        nums = [n for n, sec in self.sources if any(sec.startswith(s) for s in sections)]
        return nums[:1]


def _view(messages: list[Message]) -> _View:
    v = _View()
    pending: dict[str, tuple[str, dict[str, Any]]] = {}
    for m in messages:
        if m.role == "user" and m.content:
            v.turn += 1
            if m.content.startswith(SUPERVISOR_PREFIX):
                v.supervisor = m.content
            else:
                v.supervisor = None
                v.customer_texts.append(m.content)
                v.latest_customer = m.content
        elif m.role == "assistant" and m.tool_calls:
            for tc in m.tool_calls:
                try:
                    args = json.loads(tc.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                pending[tc.id] = (tc.name, args)
        elif m.role == "tool" and m.tool_call_id in pending:
            name, args = pending.pop(m.tool_call_id)
            try:
                body = json.loads(m.content or "{}")
            except json.JSONDecodeError:
                body = {"ok": False, "error": "unreadable"}
            v.calls.append(
                _Call(
                    name, args, bool(body.get("ok")), body.get("result"), body.get("error"), v.turn
                )
            )
            if name == "search_policy" and body.get("ok"):
                for p in body["result"]["passages"]:
                    if p["citation"] not in [n for n, _ in v.sources]:
                        v.sources.append((p["citation"], p["section"]))
    return v


def _money(x: float) -> str:
    return f"£{x:,.2f}"


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text[:2] != text[:2].upper() else text


class ScriptedAgent:
    """Callable for ``DeterministicProvider``: messages in, next tool calls out."""

    def __call__(self, request: ChatRequest) -> ChatResponse:
        view = _view(request.messages)
        calls = self.decide(view)
        return ChatResponse(
            provider="scripted",
            model="scripted-agent",
            content=None,
            tool_calls=[
                ToolCall(id=f"s{view.turn}_{len(view.calls) + i}", name=n, arguments=json.dumps(a))
                for i, (n, a) in enumerate(calls)
            ],
            finish_reason="tool_calls",
        )

    # ------------------------------------------------------------------ decisions
    def decide(self, v: _View) -> list[tuple[str, dict[str, Any]]]:  # noqa: PLR0911, PLR0912
        if v.supervisor:
            return self._after_supervisor(v)
        text = v.latest_customer
        intent = intent_of(text) or next(
            (i for i in map(intent_of, reversed(v.customer_texts)) if i), None
        )
        numbers = invoice_numbers(text) or [
            n for t in reversed(v.customer_texts) for n in invoice_numbers(t)
        ]
        inv = numbers[0] if numbers else None

        if inv is None:
            if intent is None:
                return [
                    self._reply(
                        "Hello, I can help with orders on your account: damaged or missing items, "
                        "deliveries, returns and invoice questions. Which invoice is it about?"
                    )
                ]
            listed = v.find("list_customer_invoices")
            if listed is None:
                return [("list_customer_invoices", {"limit": 5})]
            invoices = [i for i in listed.result["invoices"] if not i["is_credit_note"]]
            recent = any(w in text.lower() for w in ("last", "latest", "recent", "just", "today"))
            if recent and invoices:
                inv = invoices[0]["invoice_no"]
            else:
                options = ", ".join(f"{i['invoice_no']} ({i['date']})" for i in invoices[:3])
                return [
                    self._reply(
                        f"Which invoice is this about? Your most recent ones are {options}."
                    )
                ]

        needs_shipment = intent in {
            "damaged",
            "missing",
            "not_received",
            "late",
            "return",
            "cancel",
        }
        got = v.find("get_invoice", invoice_no=inv)
        batch: list[tuple[str, dict[str, Any]]] = []
        if got is None:
            batch.append(("get_invoice", {"invoice_no": inv}))
        if needs_shipment and v.find("get_shipment_status", invoice_no=inv) is None:
            batch.append(("get_shipment_status", {"invoice_no": inv}))
        if batch:
            return batch
        assert got is not None  # noqa: S101
        if not got.ok:
            return [
                self._reply(
                    f"I can't find invoice {inv} on your account, so I can't look into it. Could "
                    "you check the number? I can only discuss orders on your own account."
                )
            ]
        invoice = got.result
        if invoice["is_credit_note"]:
            intent = "credit"
        topic = intent or "refund"
        if v.find("search_policy", this_turn=True) is None:
            return [("search_policy", {"query": POLICY_QUERY.get(topic, "how refunds work")})]

        if topic == "credit":
            return [
                self._reply(
                    f"{inv} is a credit note: it records a cancellation or refund that has already "
                    f"been processed, so there is nothing further to refund on it"
                    f"{v.cite('Cancellations')}. If something else is wrong, tell me the invoice "
                    "number of the original order.",
                    v.cite_numbers("Cancellations"),
                )
            ]
        if topic in {"damaged", "missing"}:
            return self._items_refund(
                v, inv, invoice, "damaged" if topic == "damaged" else "missing_items"
            )
        if topic == "not_received":
            return self._not_received(v, inv)
        if topic == "late":
            return self._simple_refund(v, inv, "late_delivery")
        if topic == "return":
            return self._return(v, inv, invoice)
        if topic == "cancel":
            ship = v.find("get_shipment_status", invoice_no=inv)
            status = ship.result.get("status") if ship and ship.ok else "dispatched"
            return [
                self._reply(
                    f"Invoice {inv} has already been dispatched (status: "
                    f"{str(status).replace('_', ' ')}), so it can no longer be cancelled"
                    f"{v.cite('Cancellations')}. Once it arrives, unused items can be returned "
                    f"within 30 days for a refund{v.cite('Returns')}.",
                    v.cite_numbers("Cancellations", "Returns"),
                )
            ]
        if topic == "info":
            if "vat" in text.lower():
                if v.find("create_ticket", category="vat_invoice") is None:
                    return [
                        (
                            "create_ticket",
                            {
                                "category": "vat_invoice",
                                "priority": "low",
                                "invoice_no": inv,
                                "summary": f"Customer asked for a VAT invoice for {inv}.",
                            },
                        )
                    ]
                return [
                    self._reply(
                        f"I've asked our accounts team to send a VAT invoice for {inv} (total "
                        f"{_money(invoice['total_gbp'])}){v.cite('Invoices and VAT')}.",
                        v.cite_numbers("Invoices and VAT"),
                    )
                ]
            count = sum(p["quantity"] for p in invoice["products"])
            return [
                self._reply(
                    f"Invoice {inv} from {invoice['date'][:10]} has {len(invoice['products'])} "
                    f"products ({count} items). Goods {_money(invoice['goods_total_gbp'])}, "
                    f"shipping "
                    f"{_money(invoice['shipping_gbp'])}, total {_money(invoice['total_gbp'])}."
                )
            ]
        return [
            self._reply(
                "I can only refund what the policy covers: damaged, faulty or missing items, late "
                "or lost deliveries and returns of unused items. What went wrong with order "
                f"{inv}?{v.cite('Refunds', 'How we handle')}",
                v.cite_numbers("Refunds", "How we handle"),
            )
        ]

    # ------------------------------------------------------------------ branches
    def _items_refund(
        self, v: _View, inv: str, invoice: dict[str, Any], reason: str
    ) -> list[tuple[str, dict[str, Any]]]:
        calc = v.find("calculate_refund", invoice_no=inv, reason=reason)
        if calc is None:
            items = match_items(v.latest_customer, invoice["products"])
            if not items:
                names = ", ".join(p["description"].title() for p in invoice["products"][:4])
                return [
                    self._reply(
                        f"Which products on invoice {inv} are affected, and how many? It lists "
                        f"{names}{'…' if len(invoice['products']) > 4 else ''}."
                    )
                ]
            clean = [{k: val for k, val in i.items() if val is not None} for i in items]
            return [("calculate_refund", {"invoice_no": inv, "reason": reason, "items": clean})]
        return self._settle(v, inv, reason, calc)

    def _simple_refund(self, v: _View, inv: str, reason: str) -> list[tuple[str, dict[str, Any]]]:
        calc = v.find("calculate_refund", invoice_no=inv, reason=reason)
        if calc is None:
            return [("calculate_refund", {"invoice_no": inv, "reason": reason})]
        return self._settle(v, inv, reason, calc)

    def _settle(  # noqa: PLR0911
        self, v: _View, inv: str, reason: str, calc: _Call
    ) -> list[tuple[str, dict[str, Any]]]:
        section = {
            "damaged": "Refunds › Damaged",
            "missing_items": "Refunds › Missing",
            "late_delivery": "Delivery › Late",
            "lost_parcel": "Delivery › Lost",
        }[reason]
        if not calc.ok:
            return [
                self._reply(
                    f"I couldn't work out a refund for {inv}: {calc.error}. I've noted it so a "
                    "colleague can check."
                )
            ]
        r = calc.result
        if not r["eligible"]:
            if reason in {"damaged", "missing_items"} and "days ago" in r["explanation"]:
                if v.find("create_ticket", category="goodwill_review") is None:
                    return [
                        (
                            "create_ticket",
                            {
                                "category": "goodwill_review",
                                "priority": "low",
                                "invoice_no": inv,
                                "summary": f"Late report ({reason.replace('_', ' ')}) on {inv}: "
                                "outside the 14-day window; customer may ask for goodwill.",
                            },
                        )
                    ]
                return [
                    self._reply(
                        f"I'm sorry to hear that. I've checked invoice {inv}: "
                        f"{_lower_first(r['explanation'])}{v.cite(section)} I've opened a goodwill "
                        "review so a colleague can look at it, but I can't promise a refund.",
                        v.cite_numbers(section),
                    )
                ]
            return [
                self._reply(
                    f"I've checked invoice {inv}: {_lower_first(r['explanation'])}"
                    f"{v.cite(section)} So no refund is due under the policy.",
                    v.cite_numbers(section),
                )
            ]
        approval = v.find("request_approval", invoice_no=inv, reason=reason)
        batch: list[tuple[str, dict[str, Any]]] = []
        if approval is None:
            batch.append(
                (
                    "request_approval",
                    {"invoice_no": inv, "reason": reason, "amount": r["amount_gbp"]},
                )
            )
        if (
            reason == "lost_parcel"
            and v.find("create_ticket", category="lost_parcel_investigation") is None
        ):
            batch.append(
                (
                    "create_ticket",
                    {
                        "category": "lost_parcel_investigation",
                        "priority": "high",
                        "invoice_no": inv,
                        "summary": f"Parcel for {inv} not delivered; open a carrier investigation.",
                    },
                )
            )
        if batch:
            return batch
        assert approval is not None  # noqa: S101
        amount = _money(r["amount_gbp"])
        what = {
            "damaged": "the damaged items",
            "missing_items": "the missing items",
            "late_delivery": "the late delivery",
            "lost_parcel": "the lost parcel",
        }[reason]
        if approval.ok and approval.result["status"] == "approved":
            return [
                self._reply(
                    f"I'm sorry about {what} on invoice {inv}. I've refunded {amount} to your "
                    f"original payment method; it should arrive within 5 working days"
                    f"{v.cite(section)}.",
                    v.cite_numbers(section),
                )
            ]
        if approval.ok:
            extra = (
                " I've also opened an investigation with the carrier."
                if reason == "lost_parcel"
                else ""
            )
            return [
                self._reply(
                    f"I'm sorry about {what} on invoice {inv}. The policy covers a refund of "
                    f"{amount}{v.cite(section)}, and because it is over £50 a supervisor needs to "
                    f"approve it. I've sent it for approval and will confirm shortly.{extra}",
                    v.cite_numbers(section),
                )
            ]
        return [
            self._reply(
                f"I couldn't complete the refund for {inv} ({approval.error}). A colleague will "
                "follow up."
            )
        ]

    def _not_received(  # noqa: PLR0911
        self, v: _View, inv: str
    ) -> list[tuple[str, dict[str, Any]]]:
        ship = v.find("get_shipment_status", invoice_no=inv)
        if ship is None or not ship.ok or not ship.result.get("status"):
            return [self._reply(f"I couldn't find tracking for {inv}. A colleague will check.")]
        s = ship.result
        status = s["status"]
        if status == "lost":
            return self._simple_refund(v, inv, "lost_parcel")
        if status == "delivered_late":
            return [
                self._reply(
                    f"Tracking shows invoice {inv} was delivered on {s['delivered_on']}, "
                    f"{s['days_late']} days after the estimate. If anything was missing or "
                    "damaged, "
                    "let me know which items."
                )
            ]
        if status == "delivered":
            if v.find("create_ticket", category="lost_parcel_investigation") is None:
                return [
                    (
                        "create_ticket",
                        {
                            "category": "lost_parcel_investigation",
                            "priority": "normal",
                            "invoice_no": inv,
                            "summary": f"Carrier shows {inv} delivered on {s['delivered_on']} "
                            "but the "
                            "customer has not received it.",
                        },
                    )
                ]
            return [
                self._reply(
                    f"Tracking {s['tracking_number']} shows invoice {inv} delivered on "
                    f"{s['delivered_on']}. As you haven't received it, I've opened an "
                    "investigation "
                    "with the carrier and a colleague will update you."
                )
            ]
        if status == "returned_to_sender":
            if v.find("create_ticket", category="address_check") is None:
                return [
                    (
                        "create_ticket",
                        {
                            "category": "address_check",
                            "priority": "normal",
                            "invoice_no": inv,
                            "summary": f"Parcel for {inv} was returned to sender; confirm the "
                            "address "
                            "and resend.",
                        },
                    )
                ]
            return [
                self._reply(
                    f"The parcel for invoice {inv} could not be delivered and came back to us"
                    f"{v.cite('Delivery › Returned')}. I've asked a colleague to confirm your "
                    "address and send it again free of charge.",
                    v.cite_numbers("Delivery › Returned"),
                )
            ]
        return [
            self._reply(
                f"Invoice {inv} is on its way (tracking {s['tracking_number']}). The estimated "
                f"delivery date is {s['estimated_delivery']}"
                f"{v.cite('Delivery › Parcels in transit')}"
                ". If it hasn't arrived 10 days after that, contact us again.",
                v.cite_numbers("Delivery › Parcels in transit"),
            )
        ]

    def _return(
        self, v: _View, inv: str, invoice: dict[str, Any]
    ) -> list[tuple[str, dict[str, Any]]]:
        calc = v.find("calculate_refund", invoice_no=inv, reason="return_unused")
        if calc is None:
            items = match_items(v.latest_customer, invoice["products"])
            args: dict[str, Any] = {"invoice_no": inv, "reason": "return_unused"}
            if items:
                args["items"] = [{k: val for k, val in i.items() if val is not None} for i in items]
            return [("calculate_refund", args)]
        if not calc.ok or not calc.result["eligible"]:
            why = calc.result["explanation"] if calc.ok else calc.error
            return [
                self._reply(
                    f"I'm afraid I can't accept a return for invoice {inv}. "
                    f"{why}{v.cite('Returns')}",
                    v.cite_numbers("Returns"),
                )
            ]
        r = calc.result
        if v.find("create_ticket", category="return_request") is None:
            return [
                (
                    "create_ticket",
                    {
                        "category": "return_request",
                        "priority": "low",
                        "invoice_no": inv,
                        "summary": f"Return of unused items on {inv}; "
                        f"refund {_money(r['amount_gbp'])} "
                        "when received.",
                    },
                )
            ]
        return [
            self._reply(
                f"You can return those items from invoice {inv}. I've created a return request; "
                f"once they arrive at our warehouse we'll refund {_money(r['amount_gbp'])}. Return "
                f"postage is paid by you unless the items were damaged{v.cite('Returns')}.",
                v.cite_numbers("Returns"),
            )
        ]

    def _after_supervisor(self, v: _View) -> list[tuple[str, dict[str, Any]]]:
        text = v.supervisor or ""
        nums = invoice_numbers(text)
        inv = nums[0] if nums else ""
        amount = re.search(r"£([\d,]+\.\d{2})", text)
        money = f"£{amount.group(1)}" if amount else "the amount"
        if "Approved" in text:
            return [
                self._reply(
                    f"Good news: a supervisor has approved your refund of {money} for invoice "
                    f"{inv}. It will be paid to your original payment method within 5 working days."
                )
            ]
        if v.find("create_ticket", category="goodwill_review") is None:
            return [
                (
                    "create_ticket",
                    {
                        "category": "goodwill_review",
                        "priority": "normal",
                        "invoice_no": inv or None,
                        "summary": f"Supervisor declined the refund of {money} on {inv}; follow up "
                        "with the customer.",
                    },
                )
            ]
        return [
            self._reply(
                f"A supervisor reviewed the refund of {money} for invoice {inv} and could not "
                "approve it. I've passed your case to a colleague, who will contact you about "
                "other options."
            )
        ]

    @staticmethod
    def _reply(message: str, citations: list[int] | None = None) -> tuple[str, dict[str, Any]]:
        return ("draft_reply", {"message": message, "citations": citations or []})
