"""Ordered fall-through over providers: e.g. Groq → Cerebras → local llama.cpp →
deterministic. Every attempt is recorded so the UI can show exactly who answered and why
earlier providers were skipped."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from reluai_core.logging import get_logger
from reluai_inference.errors import AllProvidersFailedError, ProviderError
from reluai_inference.ledger import Priority, TokenLedger
from reluai_inference.providers import Provider
from reluai_inference.types import ChatRequest, ChatResponse

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Attempt:
    provider: str
    model: str
    outcome: str  # ok | not_configured | rate_limited | unavailable | budget_exhausted | ...
    detail: str | None
    latency_ms: int


@dataclass(slots=True)
class ChainResult:
    response: ChatResponse
    attempts: list[Attempt] = field(default_factory=list)

    @property
    def fell_back(self) -> bool:
        return len(self.attempts) > 1


class ProviderChain:
    def __init__(self, providers: list[Provider], ledger: TokenLedger | None = None) -> None:
        if not providers:
            raise ValueError("a chain needs at least one provider")
        self.providers = providers
        self.ledger = ledger

    def complete(
        self,
        request: ChatRequest,
        *,
        feature: str,
        visitor: str | None = None,
        priority: Priority = "visitor",
    ) -> ChainResult:
        attempts: list[Attempt] = []
        estimate = request.estimated_tokens()
        for provider in self.providers:
            t0 = time.perf_counter()
            try:
                if not provider.available():
                    attempts.append(
                        Attempt(provider.name, provider.model, "not_configured", None, 0)
                    )
                    continue
                if self.ledger:
                    self.ledger.check(
                        provider=provider.name,
                        model=provider.model,
                        visitor=visitor,
                        estimate=estimate,
                        priority=priority,
                        costs_tokens=provider.costs_tokens,
                    )
                response = provider.chat(request)
            except ProviderError as exc:
                latency = round((time.perf_counter() - t0) * 1000)
                attempts.append(
                    Attempt(provider.name, provider.model, exc.outcome, str(exc), latency)
                )
                log.warning(
                    "llm.provider_failed",
                    provider=provider.name,
                    feature=feature,
                    outcome=exc.outcome,
                )
                if self.ledger and exc.outcome not in {"budget_exhausted", "not_configured"}:
                    self.ledger.record(
                        provider=provider.name,
                        model=provider.model,
                        feature=feature,
                        visitor=visitor,
                        prompt_tokens=0,
                        completion_tokens=0,
                        latency_ms=latency,
                        outcome=exc.outcome,
                    )
                if not exc.fall_through:
                    raise
                continue
            attempts.append(Attempt(provider.name, response.model, "ok", None, response.latency_ms))
            if self.ledger:
                self.ledger.record(
                    provider=provider.name,
                    model=provider.model,
                    feature=feature,
                    visitor=visitor,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    latency_ms=response.latency_ms,
                    outcome="ok",
                )
            log.info(
                "llm.completed",
                provider=provider.name,
                model=response.model,
                feature=feature,
                tokens=response.usage.total,
                latency_ms=response.latency_ms,
                fallbacks=len(attempts) - 1,
            )
            return ChainResult(response=response, attempts=attempts)
        raise AllProvidersFailedError(list(attempts))
