from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from reluai_core.db import Database
from reluai_inference.chain import ProviderChain
from reluai_inference.config import InferenceSettings, build_chain
from reluai_inference.errors import BudgetExceededError
from reluai_inference.ledger import BudgetPolicy, TokenLedger
from reluai_inference.providers import DeterministicProvider, OpenAICompatibleProvider
from reluai_inference.types import ChatRequest, ChatResponse, Message

pytestmark = pytest.mark.db
REQ = ChatRequest(messages=[Message(role="user", content="hi")], max_tokens=100)


def groq(handler: object) -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name="groq",
        base_url="https://llm.test/v1",
        model="m",
        api_key=SecretStr("k"),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )  # type: ignore[arg-type]


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 40, "completion_tokens": 10},
        },
    )


def test_usage_is_recorded_and_daily_budget_enforced(clean_db: Database) -> None:
    ledger = TokenLedger(clean_db, BudgetPolicy(daily_tokens={"groq:m": 300}, showcase_reserve=0.0))
    det = DeterministicProvider(lambda r: ChatResponse(provider="", model="", content="rules"))
    chain = ProviderChain([groq(ok), det], ledger)
    first = chain.complete(REQ, feature="t")
    assert first.response.provider == "groq"
    assert ledger.spent_today("groq", "m") == 50
    # Pre-flight estimate is 100 tokens and each call spends 50: a call is allowed while
    # spent + 100 <= 300, i.e. five calls in total, then the chain falls through.
    providers = [chain.complete(REQ, feature="t").response.provider for _ in range(5)]
    assert providers == ["groq"] * 4 + ["deterministic"]
    last = chain.complete(REQ, feature="t")
    assert last.attempts[0].outcome == "budget_exhausted"
    assert ledger.spent_today("groq", "m") == 250


def test_showcase_reserve_is_kept_for_scheduled_runs(clean_db: Database) -> None:
    ledger = TokenLedger(
        clean_db, BudgetPolicy(daily_tokens={"groq:m": 1000}, showcase_reserve=0.5)
    )
    ledger.record(
        provider="groq",
        model="m",
        feature="t",
        visitor=None,
        prompt_tokens=450,
        completion_tokens=0,
        latency_ms=1,
        outcome="ok",
    )
    with pytest.raises(BudgetExceededError):
        ledger.check(
            provider="groq",
            model="m",
            visitor="v",
            estimate=100,
            priority="visitor",
            costs_tokens=True,
        )
    ledger.check(
        provider="groq",
        model="m",
        visitor=None,
        estimate=100,
        priority="showcase",
        costs_tokens=True,
    )


def test_per_visitor_allowance(clean_db: Database) -> None:
    ledger = TokenLedger(clean_db, BudgetPolicy(visitor_daily_tokens=120))
    ledger.record(
        provider="groq",
        model="m",
        feature="t",
        visitor="abc",
        prompt_tokens=100,
        completion_tokens=0,
        latency_ms=1,
        outcome="ok",
    )
    with pytest.raises(BudgetExceededError, match="visitor"):
        ledger.check(
            provider="groq",
            model="m",
            visitor="abc",
            estimate=50,
            priority="visitor",
            costs_tokens=True,
        )
    ledger.check(
        provider="groq",
        model="m",
        visitor="other",
        estimate=50,
        priority="visitor",
        costs_tokens=True,
    )


def test_build_chain_orders_providers(clean_db: Database) -> None:
    s = InferenceSettings(
        groq_api_key=SecretStr("k"), cerebras_api_key=SecretStr("c"), local_enabled=True
    )
    chain = build_chain(
        s,
        clean_db,
        role="fast",
        deterministic=lambda r: ChatResponse(provider="", model="", content=""),
    )
    assert [p.name for p in chain.providers] == ["groq", "cerebras", "local", "deterministic"]
    assert chain.providers[0].model == s.groq_fast_model
