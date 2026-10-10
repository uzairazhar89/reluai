"""Public API of the Customer Support Agent (mounted at ``/api/support``)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from reluai_core.db import Database, DatabaseDep
from reluai_core.errors import ProblemError
from reluai_core.http import client_ip
from reluai_core.ratelimit import consume_quota, visitor_key
from reluai_inference.chain import ProviderChain
from reluai_inference.config import build_chain, configured_providers, get_inference_settings
from reluai_support import service
from reluai_support.agent import scripted_provider
from reluai_support.schemas import (
    CatalogueOut,
    ConversationOut,
    DecisionRequest,
    EvaluationRunOut,
    MessageRequest,
    PolicySectionOut,
    StartRequest,
)
from reluai_support.settings import SupportSettings, get_support_settings

router = APIRouter(tags=["support"])
SettingsDep = Annotated[SupportSettings, Depends(get_support_settings)]
ChainFactory = Callable[[], ProviderChain]


def _visitor(request: Request) -> str:
    secret = request.app.state.core_settings.visitor_hash_secret.get_secret_value()
    return visitor_key(client_ip(request), secret)


def _quota(db: Database, key: str, limit: int, what: str) -> None:
    with db.session() as s:
        result = consume_quota(s, key=key, limit=limit, window=timedelta(hours=1))
    if not result.allowed:
        raise ProblemError(
            429,
            f"Limit of {limit} {what} per hour reached; try again later.",
            code="quota_exceeded",
            headers={"Retry-After": str(result.retry_after_seconds)},
        )


def _chain_factory(request: Request, db: Database) -> ChainFactory:
    """Free-tier models first (when configured), the scripted agent last."""
    override: ChainFactory | None = getattr(request.app.state, "support_chain_factory", None)
    if override is not None:
        return override

    def factory() -> ProviderChain:
        chain = build_chain(get_inference_settings(), db, role="answer")
        return ProviderChain([*chain.providers, scripted_provider()], chain.ledger)

    return factory


def _llm_available(request: Request) -> bool:
    override: ChainFactory | None = getattr(request.app.state, "support_chain_factory", None)
    if override is not None:
        return any(p.available() and p.name != "scripted" for p in override().providers)
    return bool(configured_providers(get_inference_settings()))


def _problem(exc: service.ConversationError) -> ProblemError:
    return ProblemError(exc.status, exc.message, code=exc.code)


def _unavailable(exc: FileNotFoundError) -> ProblemError:
    return ProblemError(
        503, "The order data is not available on this server.", code="orders_unavailable"
    )


@router.get("/catalogue", response_model=CatalogueOut)
def get_catalogue(request: Request, settings: SettingsDep) -> CatalogueOut:
    """Scenarios, sample customers and the desk's settings."""
    try:
        return service.catalogue(settings, llm_available=_llm_available(request))
    except FileNotFoundError as exc:
        raise _unavailable(exc) from exc


@router.get("/policy", response_model=list[PolicySectionOut])
def get_policy() -> list[PolicySectionOut]:
    """The customer service policy the agent searches (written for this demo)."""
    return service.policy_sections()


@router.post("/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
def post_conversation(
    body: StartRequest, request: Request, db: DatabaseDep, settings: SettingsDep
) -> ConversationOut:
    """Start a conversation from a scenario or a customer and message; runs the first turn."""
    visitor = _visitor(request)
    _quota(db, f"support:start:{visitor}", settings.visitor_conversations_per_hour, "conversations")
    _quota(db, f"support:msg:{visitor}", settings.visitor_messages_per_hour, "messages")
    try:
        return service.start(
            db,
            settings,
            visitor=visitor,
            chain_factory=_chain_factory(request, db),
            scenario_id=body.scenario_id,
            customer_id=body.customer_id,
            message=body.message,
        )
    except service.ConversationError as exc:
        raise _problem(exc) from exc
    except FileNotFoundError as exc:
        raise _unavailable(exc) from exc


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def get_conversation(
    conversation_id: uuid.UUID, db: DatabaseDep, settings: SettingsDep
) -> ConversationOut:
    try:
        return service.get(db, settings, conversation_id)
    except service.ConversationError as exc:
        raise _problem(exc) from exc


@router.post("/conversations/{conversation_id}/messages", response_model=ConversationOut)
def post_message(
    conversation_id: uuid.UUID,
    body: MessageRequest,
    request: Request,
    db: DatabaseDep,
    settings: SettingsDep,
) -> ConversationOut:
    """The customer's next message."""
    visitor = _visitor(request)
    _quota(db, f"support:msg:{visitor}", settings.visitor_messages_per_hour, "messages")
    try:
        return service.reply(
            db,
            settings,
            conversation_id,
            visitor=visitor,
            chain_factory=_chain_factory(request, db),
            message=body.message,
        )
    except service.ConversationError as exc:
        raise _problem(exc) from exc
    except FileNotFoundError as exc:
        raise _unavailable(exc) from exc


@router.post("/conversations/{conversation_id}/approval", response_model=ConversationOut)
def post_approval(
    conversation_id: uuid.UUID,
    body: DecisionRequest,
    request: Request,
    db: DatabaseDep,
    settings: SettingsDep,
) -> ConversationOut:
    """The supervisor's decision on a pending refund (the visitor plays the supervisor)."""
    visitor = _visitor(request)
    _quota(db, f"support:msg:{visitor}", settings.visitor_messages_per_hour, "messages")
    try:
        return service.decide(
            db,
            settings,
            conversation_id,
            visitor=visitor,
            chain_factory=_chain_factory(request, db),
            approve=body.decision == "approve",
            note=body.note,
        )
    except service.ConversationError as exc:
        raise _problem(exc) from exc
    except FileNotFoundError as exc:
        raise _unavailable(exc) from exc


@router.get("/evaluation", response_model=list[EvaluationRunOut])
def get_evaluation(db: DatabaseDep) -> list[EvaluationRunOut]:
    """The latest scenario-suite run for each provider label (empty until one has run)."""
    return service.latest_evaluations(db)
