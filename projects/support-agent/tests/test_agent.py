"""Tools and the agent loop, with the scripted agent and with a fake model."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

from reluai_inference.chain import ProviderChain
from reluai_inference.providers import DeterministicProvider
from reluai_inference.types import ChatRequest, ChatResponse, ToolCall, Usage
from reluai_support.agent import AgentRuntime, decide_approval, new_session, run_turn
from reluai_support.tools import (
    CalculateRefundArgs,
    DraftReplyArgs,
    GetInvoiceArgs,
    ListInvoicesArgs,
    RequestApprovalArgs,
    SearchPolicyArgs,
)

from .conftest import CUSTOMER, OTHER, Fixture


def ctx_for(runtime: AgentRuntime, customer: int = CUSTOMER):  # type: ignore[no-untyped-def]
    return runtime.context(new_session(runtime, customer))


# ---------------------------------------------------------------- tools
def test_tools_only_see_the_customers_own_invoices(
    runtime: AgentRuntime, fixture_orders: Fixture
) -> None:
    ctx = ctx_for(runtime)
    assert ctx.get_invoice(GetInvoiceArgs(invoice_no=fixture_orders.invoices["recent"]))
    with pytest.raises(LookupError, match="No invoice"):
        ctx.get_invoice(GetInvoiceArgs(invoice_no=fixture_orders.invoices["other"]))
    with pytest.raises(LookupError, match="No invoice"):
        ctx.get_invoice(GetInvoiceArgs(invoice_no="999999"))
    listed = ctx.list_customer_invoices(ListInvoicesArgs())
    assert fixture_orders.invoices["other"] not in {i["invoice_no"] for i in listed["invoices"]}


def test_refund_amounts_only_come_from_the_rules(
    runtime: AgentRuntime, fixture_orders: Fixture
) -> None:
    ctx = ctx_for(runtime)
    inv = fixture_orders.invoices["recent"]
    with pytest.raises(ValueError, match="calculate_refund"):
        ctx.request_approval(RequestApprovalArgs(invoice_no=inv, reason="damaged", amount=7.5))
    calc = ctx.calculate_refund(
        CalculateRefundArgs(
            invoice_no=inv, reason="damaged", items=[{"stock_code": "21481", "quantity": 2}]
        )  # type: ignore[list-item]
    )
    assert calc["amount_gbp"] == 7.5
    with pytest.raises(ValueError, match=r"exactly £7\.50"):
        ctx.request_approval(RequestApprovalArgs(invoice_no=inv, reason="damaged", amount=500))
    ok = ctx.request_approval(RequestApprovalArgs(invoice_no=inv, reason="damaged", amount=7.5))
    assert ok["status"] == "approved"
    again = ctx.request_approval(RequestApprovalArgs(invoice_no=inv, reason="damaged", amount=7.5))
    assert "already" in again["note"]
    assert [r.amount for r in ctx.session.refunds] == [7.5]


def test_large_refunds_wait_for_a_supervisor(
    runtime: AgentRuntime, fixture_orders: Fixture
) -> None:
    ctx = ctx_for(runtime)
    inv = fixture_orders.invoices["lost"]
    ctx.calculate_refund(CalculateRefundArgs(invoice_no=inv, reason="lost_parcel"))
    result = ctx.request_approval(
        RequestApprovalArgs(invoice_no=inv, reason="lost_parcel", amount=166.5)
    )
    assert result["status"] == "pending_supervisor"
    assert ctx.session.refunds == []
    assert ctx.session.pending_approval is not None


def test_replies_can_only_cite_retrieved_passages(runtime: AgentRuntime) -> None:
    ctx = ctx_for(runtime)
    with pytest.raises(ValueError, match="do not match"):
        ctx.draft_reply(DraftReplyArgs(message="See [1].", citations=[1]))
    found = ctx.search_policy(SearchPolicyArgs(query="damaged items refund"))
    assert found["passages"][0]["citation"] == 1
    ctx.draft_reply(DraftReplyArgs(message="See [1].", citations=[1]))
    assert ctx.session.reply == "See [1]."


# ---------------------------------------------------------------- scripted agent
def test_scripted_damage_refund(runtime: AgentRuntime, fixture_orders: Fixture) -> None:
    inv = fixture_orders.invoices["recent"]
    session = run_turn(
        runtime,
        new_session(runtime, CUSTOMER),
        f"Invoice {inv}: 2 of the fawn blue hot water bottles arrived cracked.",
    )
    assert [(r.amount, r.approved_by) for r in session.refunds] == [(7.5, "agent")]
    assert session.status == "active"
    assert "£7.50" in (session.reply or "")
    names = [s.name for s in session.steps if s.kind == "tool"]
    assert names[:2] == ["get_invoice", "get_shipment_status"]  # one step, two calls
    first_model_step = next(s for s in session.steps if s.kind == "model")
    assert first_model_step.provider == "scripted"
    assert session.transcript[-1].citations  # cites the policy passage


def test_supervisor_flow(runtime: AgentRuntime, fixture_orders: Fixture) -> None:
    inv = fixture_orders.invoices["lost"]
    session = run_turn(runtime, new_session(runtime, CUSTOMER), f"Order {inv} never arrived.")
    assert session.status == "awaiting_approval"
    assert {t.category for t in session.tickets} == {"lost_parcel_investigation"}
    decide_approval(runtime, session, approve=True)
    assert [(r.amount, r.approved_by) for r in session.refunds] == [(166.5, "supervisor")]
    assert session.status == "active"
    assert [t.role for t in session.transcript] == ["customer", "agent", "supervisor", "agent"]
    with pytest.raises(LookupError):
        decide_approval(runtime, session, approve=True)


def test_rejected_refund_is_not_paid(runtime: AgentRuntime, fixture_orders: Fixture) -> None:
    inv = fixture_orders.invoices["lost"]
    session = run_turn(runtime, new_session(runtime, CUSTOMER), f"Order {inv} never arrived.")
    decide_approval(runtime, session, approve=False, note="Wait for the carrier.")
    assert session.refunds == []
    assert session.approvals[0].status == "rejected"
    assert "could not approve" in (session.reply or "")


def test_another_customers_invoice_is_refused(
    runtime: AgentRuntime, fixture_orders: Fixture
) -> None:
    other = fixture_orders.invoices["other"]
    session = run_turn(
        runtime, new_session(runtime, CUSTOMER), f"Order {other}: the cakestands are smashed."
    )
    assert session.refunds == [] and session.approvals == []
    assert "can't find invoice" in (session.reply or "")
    assert new_session(runtime, OTHER).customer_id == OTHER


# ---------------------------------------------------------------- a fake model
def fake_model(script: list[list[tuple[str, dict[str, Any]]] | str]) -> Callable[[], ProviderChain]:
    """A provider that replays tool calls (or a text answer) one step at a time."""
    steps = list(script)
    seen: list[ChatRequest] = []

    def handler(request: ChatRequest) -> ChatResponse:
        seen.append(request)
        step = steps.pop(0) if steps else "out of script"
        if isinstance(step, str):
            return ChatResponse(provider="", model="", content=step)
        return ChatResponse(
            provider="",
            model="",
            content=None,
            tool_calls=[
                ToolCall(id=f"c{len(seen)}_{i}", name=n, arguments=json.dumps(a))
                for i, (n, a) in enumerate(step)
            ],
            usage=Usage(prompt_tokens=1000, completion_tokens=50),
        )

    factory = lambda: ProviderChain([DeterministicProvider(handler, name="fake", model="m")])  # noqa: E731
    factory.seen = seen  # type: ignore[attr-defined]
    return factory


def test_model_errors_are_returned_and_corrected(
    runtime: AgentRuntime, fixture_orders: Fixture
) -> None:
    inv = fixture_orders.invoices["recent"]
    runtime.chain_factory = fake_model(
        [
            [("get_invoice", {"invoice_no": "not-a-number"}), ("teleport", {})],
            [("get_invoice", {"invoice_no": inv}), ("search_policy", {"query": "damaged"})],
            [("calculate_refund", {"invoice_no": inv, "reason": "damaged",
                                   "items": [{"stock_code": "21481", "quantity": 1}]})],
            [("request_approval", {"invoice_no": inv, "reason": "damaged", "amount": 99})],
            [("request_approval", {"invoice_no": inv, "reason": "damaged", "amount": 3.75})],
            [("draft_reply", {"message": "Refunded £3.75 [1].", "citations": [1]})],
        ]
    )  # fmt: skip
    session = run_turn(runtime, new_session(runtime, CUSTOMER), "One bottle cracked.")
    tool_steps = [s for s in session.steps if s.kind == "tool"]
    assert [s.ok for s in tool_steps] == [False, False, True, True, True, False, True, True]
    assert "validation" in tool_steps[0].result["error"]
    assert "unknown tool" in tool_steps[1].result["error"]
    assert "exactly £3.75" in tool_steps[5].result["error"]
    assert [r.amount for r in session.refunds] == [3.75]
    assert session.reply == "Refunded £3.75 [1]."
    assert session.tokens == 6 * 1050
    assert session.providers == ["fake"]


def test_text_answers_and_step_limits(runtime: AgentRuntime) -> None:
    runtime.chain_factory = fake_model(["Hello! How can I help?"])
    session = run_turn(runtime, new_session(runtime, CUSTOMER), "Hi")
    assert session.reply == "Hello! How can I help?"

    runtime.chain_factory = fake_model([[("list_customer_invoices", {})]] * 20)
    runtime.max_steps = 3
    session = run_turn(runtime, new_session(runtime, CUSTOMER), "Hi")
    assert any(t.category == "other" for t in session.tickets)  # handed to a person
    assert "colleague" in (session.reply or "")
    assert sum(1 for s in session.steps if s.kind == "model") == 3


def test_falls_back_to_the_scripted_agent(runtime: AgentRuntime, fixture_orders: Fixture) -> None:
    from reluai_support.agent import scripted_provider

    class Down:
        name, model, costs_tokens = "groq", "m", True

        def available(self) -> bool:
            return False

        def chat(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover
            raise AssertionError

    runtime.chain_factory = lambda: ProviderChain([Down(), scripted_provider()])
    inv = fixture_orders.invoices["transit"]
    session = run_turn(runtime, new_session(runtime, CUSTOMER), f"Where is my order {inv}?")
    model_steps = [s for s in session.steps if s.kind == "model"]
    assert model_steps[0].provider == "scripted"
    assert model_steps[0].note == "fell back after groq: not_configured"
    assert "on its way" in (session.reply or "")
