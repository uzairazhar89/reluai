"""Scenario evaluation: run every scenario through the agent and check the outcome.

A scenario passes when all of these hold:

- the refunds recorded match the expectation exactly (invoice, reason, and the amount the
  refund rules give for the expected items), or none were recorded when none are due;
- for refunds above the agent's limit, approval was requested for that amount and the
  scripted supervisor decision was applied;
- every expected ticket category was opened;
- a reply was drafted and mentions what it must (invoice number, amounts);
- the expected tools were used, and the turn did not end in an automatic hand-over.

The same scenarios run against any provider chain, so the scripted baseline and each model
are measured identically.
"""

from __future__ import annotations

import os
import platform
import statistics
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Any

from reluai_inference.chain import ProviderChain
from reluai_support.agent import AgentRuntime, decide_approval, new_session, run_turn
from reluai_support.refunds import ItemRequest, calculate_refund
from reluai_support.scenarios import SCENARIOS, Scenario
from reluai_support.shipments import shipment_for
from reluai_support.state import SessionState


@dataclass
class ScenarioResult:
    id: str
    title: str
    category: str
    passed: bool
    failures: list[str]
    steps: int
    model_calls: int
    tool_calls: int
    tool_errors: int
    tokens: int
    latency_ms: int
    providers: list[str]
    provider_errors: int = 0  # steps where no provider could answer (outage, quota)
    refunds: list[dict[str, Any]] = field(default_factory=list)
    tickets: list[str] = field(default_factory=list)
    reply: str | None = None


def expected_amount(rt: AgentRuntime, sc: Scenario) -> float | None:
    e = sc.expect
    if e.outcome == "no_refund" or e.invoice_no is None or e.reason is None:
        return None
    invoice = rt.store.invoice(e.invoice_no)
    if invoice is None:
        raise LookupError(f"{sc.id}: invoice {e.invoice_no} not in the snapshot")
    decision = calculate_refund(
        invoice,
        shipment_for(invoice.header, rt.as_of),
        e.reason,
        [ItemRequest(code, qty) for code, qty in e.items] or None,
        as_of=rt.as_of,
        auto_approve_limit=rt.auto_approve_limit,
    )
    if not decision.eligible:
        raise ValueError(f"{sc.id}: expected a refund but the rules say: {decision.explanation}")
    return decision.amount


def check(rt: AgentRuntime, sc: Scenario, session: SessionState) -> list[str]:
    e = sc.expect
    problems: list[str] = []
    amount = expected_amount(rt, sc)
    refunds = [(r.invoice_no, r.reason, round(r.amount, 2)) for r in session.refunds]
    requested = [(a.invoice_no, a.reason, round(a.amount, 2)) for a in session.approvals]
    if e.outcome == "refund":
        want = (e.invoice_no, e.reason, amount)
        if refunds != [want]:
            problems.append(f"refunds {refunds}, expected [{want}]")
    elif e.outcome == "refund_rejected":
        want = (e.invoice_no, e.reason, amount)
        if want not in requested:
            problems.append(f"approval requests {requested}, expected {want}")
        if refunds:
            problems.append(f"refunds {refunds} after a rejected approval")
    else:
        if refunds:
            problems.append(f"refunded {refunds} although none is due")
        if requested:
            problems.append(f"requested approval for {requested} although none is due")
    created = {t.category for t in session.tickets}
    problems.extend(
        f"no {category} ticket (tickets: {sorted(created) or 'none'})"
        for category in e.tickets
        if category not in created
    )
    reply = " ".join(t.text for t in session.transcript if t.role == "agent")
    if not reply:
        problems.append("no reply drafted")
    problems.extend(
        f"reply does not mention {text!r}"
        for text in e.mentions
        if text.lower() not in reply.lower()
    )
    if amount is not None and e.outcome == "refund" and f"{amount:,.2f}" not in reply:
        problems.append(f"reply does not state the amount £{amount:,.2f}")
    used = {s.name for s in session.steps if s.kind == "tool"}
    problems.extend(f"did not use {tool}" for tool in e.tools if tool not in used)
    if any(s.note and s.note.startswith("automatic hand-over") for s in session.steps):
        problems.append("ended in an automatic hand-over")
    return problems


def run_scenario(rt: AgentRuntime, sc: Scenario) -> tuple[ScenarioResult, SessionState]:
    t0 = time.perf_counter()
    session = new_session(rt, sc.customer_id, scenario_id=sc.id)
    run_turn(rt, session, sc.message)
    if session.pending_approval is not None and sc.approve is not None:
        decide_approval(
            rt,
            session,
            approve=sc.approve,
            note=None if sc.approve else "Declined in the scenario script.",
        )
    failures = check(rt, sc, session)
    tool_steps = [s for s in session.steps if s.kind == "tool"]
    result = ScenarioResult(
        id=sc.id,
        title=sc.title,
        category=sc.category,
        passed=not failures,
        failures=failures,
        steps=len(session.steps),
        model_calls=sum(1 for s in session.steps if s.kind == "model"),
        tool_calls=len(tool_steps),
        tool_errors=sum(1 for s in tool_steps if not s.ok),
        tokens=session.tokens,
        latency_ms=round((time.perf_counter() - t0) * 1000),
        providers=list(session.providers),
        provider_errors=sum(
            1 for s in session.steps if s.kind == "model" and s.name == "no provider"
        ),
        refunds=[r.model_dump(mode="json") for r in session.refunds],
        tickets=[t.category for t in session.tickets],
        reply=session.reply,
    )
    return result, session


@dataclass
class EvaluationSummary:
    label: str
    scenarios: int
    passed: int
    by_category: dict[str, list[int]]
    tokens: int
    median_latency_ms: int
    p95_latency_ms: int
    providers: list[str]
    environment: dict[str, Any]
    results: list[ScenarioResult]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def run_evaluation(
    rt_factory: Callable[[Callable[[], ProviderChain]], AgentRuntime],
    chain_factory: Callable[[], ProviderChain],
    *,
    label: str,
    scenarios: tuple[Scenario, ...] = SCENARIOS,
) -> EvaluationSummary:
    rt = rt_factory(chain_factory)
    results = [run_scenario(rt, sc)[0] for sc in scenarios]
    latencies = sorted(r.latency_ms for r in results) or [0]
    by_category: dict[str, list[int]] = {}
    for r in results:
        passed_total = by_category.setdefault(r.category, [0, 0])
        passed_total[0] += int(r.passed)
        passed_total[1] += 1
    providers = sorted({p for r in results for p in r.providers})
    return EvaluationSummary(
        label=label,
        scenarios=len(results),
        passed=sum(r.passed for r in results),
        by_category=by_category,
        tokens=sum(r.tokens for r in results),
        median_latency_ms=round(statistics.median(latencies)),
        p95_latency_ms=latencies[min(len(latencies) - 1, round(0.95 * (len(latencies) - 1)))],
        providers=providers,
        environment={
            "cpus": os.cpu_count(),
            "python": platform.python_version(),
            "as_of": rt.as_of.isoformat(),
            "auto_approve_limit": rt.auto_approve_limit,
            "max_steps": rt.max_steps,
        },
        results=results,
    )
