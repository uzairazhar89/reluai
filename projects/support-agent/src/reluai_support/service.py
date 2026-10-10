"""Conversations for the website: start, continue, approve, read; evaluations and catalogue."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from reluai_core.db import Database
from reluai_core.logging import get_logger
from reluai_inference.chain import ProviderChain
from reluai_retrieval.chunking import chunk_text
from reluai_retrieval.search import Hit, search
from reluai_support.agent import AgentRuntime, decide_approval, new_session, run_turn
from reluai_support.evaluation import EvaluationSummary
from reluai_support.models import Conversation, EvaluationRun
from reluai_support.orders import OrderStore
from reluai_support.policy import COLLECTION, POLICY_TEXT, ensure_policy_indexed
from reluai_support.scenarios import SCENARIOS, by_id
from reluai_support.schemas import (
    ApprovalOut,
    CatalogueOut,
    ConversationOut,
    CustomerOut,
    EvaluationResultOut,
    EvaluationRunOut,
    InvoiceSummary,
    PolicySectionOut,
    RefundOut,
    SourceOut,
    SupportScenarioOut,
    TicketOut,
    TraceStepOut,
    TranscriptOut,
)
from reluai_support.settings import SupportSettings
from reluai_support.state import SessionState

log = get_logger(__name__)
ChainFactory = Callable[[], ProviderChain]
_indexed = threading.Event()
_index_lock = threading.Lock()


class ConversationError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def policy_search(db: Database) -> Callable[[str, int], list[Hit]]:
    """Full-text search over the policy, indexing it once per process if needed."""
    if not _indexed.is_set():
        with _index_lock, db.session() as s:
            if not _indexed.is_set():
                ensure_policy_indexed(s)
                _indexed.set()

    def run(query: str, k: int) -> list[Hit]:
        with db.session() as s:
            return search(s, COLLECTION, query, k=k).hits

    return run


def runtime(
    db: Database, settings: SupportSettings, chain_factory: ChainFactory, visitor: str | None
) -> AgentRuntime:
    return AgentRuntime(
        store=OrderStore(settings.orders_db),
        policy_search=policy_search(db),
        chain_factory=chain_factory,
        as_of=settings.as_of,
        auto_approve_limit=settings.auto_approve_limit_gbp,
        max_steps=settings.max_steps_per_turn,
        deadline_seconds=settings.turn_deadline_seconds,
        visitor=visitor,
    )


# --------------------------------------------------------------------------- catalogue
@lru_cache(maxsize=4)
def _customers(path: str) -> list[CustomerOut]:
    store = OrderStore(Path(path))
    seen: list[int] = []
    for sc in SCENARIOS:
        if sc.customer_id not in seen and not sc.id.startswith(("access", "inject")):
            seen.append(sc.customer_id)
    out: list[CustomerOut] = []
    for cid in seen[:12]:
        summary = store.customer_summary(cid)
        if summary is None:
            continue
        country, invoices, first, last = summary
        out.append(
            CustomerOut(
                customer_id=cid,
                country=country,
                invoices=invoices,
                first_order=first.date(),
                last_order=last.date(),
                recent=[
                    InvoiceSummary(
                        invoice_no=h.invoice_no,
                        date=h.invoiced_at.date(),
                        total_gbp=round(h.total, 2),
                        is_credit_note=h.is_credit_note,
                    )
                    for h in store.customer_invoices(cid, limit=5)
                ],
            )
        )
    return out


def catalogue(settings: SupportSettings, *, llm_available: bool) -> CatalogueOut:
    return CatalogueOut(
        as_of=settings.as_of,
        auto_approve_limit_gbp=settings.auto_approve_limit_gbp,
        scenarios=[
            SupportScenarioOut(
                id=s.id,
                title=s.title,
                category=s.category,
                customer_id=s.customer_id,
                message=s.message,
                needs_supervisor=s.approve is not None,
            )
            for s in SCENARIOS
        ],
        customers=_customers(str(settings.orders_db)),
        llm_available=llm_available,
    )


def policy_sections() -> list[PolicySectionOut]:
    sections: dict[str, list[str]] = {}
    for chunk in chunk_text(POLICY_TEXT, max_words=400, overlap=0):
        sections.setdefault(chunk.heading, []).append(chunk.text)
    return [PolicySectionOut(heading=h, text="\n\n".join(t)) for h, t in sections.items()]


# --------------------------------------------------------------------------- conversations
def _out(state: SessionState, settings: SupportSettings) -> ConversationOut:
    return ConversationOut(
        id=state.id,
        customer_id=state.customer_id,
        scenario_id=state.scenario_id,
        status=state.status,
        turn=state.turn,
        can_reply=state.status == "active"
        and sum(1 for t in state.transcript if t.role == "customer") < settings.max_customer_turns,
        transcript=[TranscriptOut(**t.model_dump()) for t in state.transcript],
        steps=[TraceStepOut(**s.model_dump()) for s in state.steps],
        sources=[
            SourceOut(number=i, heading=s.heading, quote=s.quote)
            for i, s in enumerate(state.sources, start=1)
        ],
        approvals=[
            ApprovalOut(
                id=a.id,
                invoice_no=a.invoice_no,
                reason=a.reason,
                amount_gbp=a.amount,
                status=a.status,
                decided_by=a.decided_by,
                note=a.note,
            )
            for a in state.approvals
        ],
        refunds=[
            RefundOut(
                invoice_no=r.invoice_no,
                reason=r.reason,
                amount_gbp=r.amount,
                approved_by=r.approved_by,
            )
            for r in state.refunds
        ],
        tickets=[
            TicketOut(
                id=t.id,
                category=t.category,
                priority=t.priority,
                invoice_no=t.invoice_no,
                summary=t.summary,
            )
            for t in state.tickets
        ],
        providers=state.providers,
        tokens=state.tokens,
    )


def _save(db: Database, state: SessionState, visitor: str, *, new: bool) -> None:
    payload = state.model_dump(mode="json")
    with db.session() as s:
        row = None if new else s.get(Conversation, state.id)
        if row is None:
            row = Conversation(id=state.id, visitor_key=visitor)
            s.add(row)
        row.customer_id = state.customer_id
        row.scenario_id = state.scenario_id
        row.status = state.status
        row.turns = state.turn
        row.tokens = state.tokens
        row.providers = list(state.providers)
        row.state = payload
        row.updated_at = datetime.now(UTC)


def _load(db: Database, conversation_id: uuid.UUID) -> tuple[SessionState, str]:
    with db.session() as s:
        row = s.get(Conversation, conversation_id)
        if row is None:
            raise ConversationError(
                404, "conversation_not_found", "This conversation has expired or does not exist."
            )
        return SessionState.model_validate(row.state), row.visitor_key


def start(
    db: Database,
    settings: SupportSettings,
    *,
    visitor: str,
    chain_factory: ChainFactory,
    scenario_id: str | None,
    customer_id: int | None,
    message: str | None,
) -> ConversationOut:
    if scenario_id is not None:
        sc = by_id(scenario_id)
        if sc is None:
            raise ConversationError(404, "scenario_not_found", "There is no such scenario.")
        customer_id, message = sc.customer_id, sc.message
    assert customer_id is not None  # noqa: S101 - validated by StartRequest
    assert message is not None  # noqa: S101
    rt = runtime(db, settings, chain_factory, visitor)
    try:
        state = new_session(rt, customer_id, scenario_id=scenario_id)
    except LookupError as exc:
        raise ConversationError(
            404, "customer_not_found", "There is no customer with orders under that ID."
        ) from exc
    run_turn(rt, state, " ".join(message.split()))
    _save(db, state, visitor, new=True)
    return _out(state, settings)


def reply(
    db: Database,
    settings: SupportSettings,
    conversation_id: uuid.UUID,
    *,
    visitor: str,
    chain_factory: ChainFactory,
    message: str,
) -> ConversationOut:
    state, owner = _load(db, conversation_id)
    if owner != visitor:
        raise ConversationError(
            403,
            "not_your_conversation",
            "Only the visitor who started this conversation can continue it.",
        )
    if state.status == "awaiting_approval":
        raise ConversationError(
            409, "awaiting_approval", "A refund is waiting for the supervisor's decision first."
        )
    if not _out(state, settings).can_reply:
        raise ConversationError(
            409,
            "conversation_finished",
            "This conversation has reached its message limit; start a new one.",
        )
    rt = runtime(db, settings, chain_factory, visitor)
    run_turn(rt, state, " ".join(message.split()))
    _save(db, state, visitor, new=False)
    return _out(state, settings)


def decide(
    db: Database,
    settings: SupportSettings,
    conversation_id: uuid.UUID,
    *,
    visitor: str,
    chain_factory: ChainFactory,
    approve: bool,
    note: str | None,
) -> ConversationOut:
    state, owner = _load(db, conversation_id)
    if owner != visitor:
        raise ConversationError(
            403,
            "not_your_conversation",
            "Only the visitor who started this conversation can decide on its refunds.",
        )
    if state.pending_approval is None:
        raise ConversationError(409, "nothing_to_approve", "No refund is waiting for approval.")
    rt = runtime(db, settings, chain_factory, visitor)
    decide_approval(rt, state, approve=approve, note=note)
    _save(db, state, visitor, new=False)
    return _out(state, settings)


def get(db: Database, settings: SupportSettings, conversation_id: uuid.UUID) -> ConversationOut:
    state, _ = _load(db, conversation_id)
    return _out(state, settings)


def purge(db: Database, settings: SupportSettings) -> int:
    cutoff = datetime.now(UTC) - timedelta(hours=settings.conversation_ttl_hours)
    with db.session() as s:
        result = s.execute(delete(Conversation).where(Conversation.updated_at < cutoff))
        return int(result.rowcount or 0)  # type: ignore[attr-defined]


# --------------------------------------------------------------------------- evaluations
def record_evaluation(db: Database, summary: EvaluationSummary) -> None:
    data: dict[str, Any] = summary.as_dict()
    with db.session() as s:
        s.add(
            EvaluationRun(
                label=summary.label,
                scenarios=summary.scenarios,
                passed=summary.passed,
                tokens=summary.tokens,
                median_latency_ms=summary.median_latency_ms,
                p95_latency_ms=summary.p95_latency_ms,
                providers=summary.providers,
                by_category=summary.by_category,
                environment=summary.environment,
                results=data["results"],
            )
        )


def latest_evaluations(db: Database) -> list[EvaluationRunOut]:
    with db.session() as s:
        rows = s.scalars(select(EvaluationRun).order_by(EvaluationRun.ran_at.desc())).all()
        latest: dict[str, EvaluationRun] = {}
        for r in rows:
            latest.setdefault(r.label, r)
        return [
            EvaluationRunOut(
                label=r.label,
                ran_at=r.ran_at,
                scenarios=r.scenarios,
                passed=r.passed,
                tokens=r.tokens,
                median_latency_ms=r.median_latency_ms,
                p95_latency_ms=r.p95_latency_ms,
                providers=r.providers,
                by_category=r.by_category,
                environment=r.environment,
                results=[EvaluationResultOut.model_validate(x) for x in r.results],
            )
            for r in sorted(latest.values(), key=lambda r: r.label)
        ]
