"""LLM configuration (env prefix ``RELUAI_LLM_``) and chain construction."""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Literal

import httpx
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from reluai_core.db import Database
from reluai_inference.chain import ProviderChain
from reluai_inference.ledger import BudgetPolicy, TokenLedger
from reluai_inference.providers import DeterministicProvider, OpenAICompatibleProvider, Provider
from reluai_inference.types import ChatRequest, ChatResponse

Role = Literal["fast", "answer"]


class InferenceSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RELUAI_LLM_", env_file=".env", extra="ignore")

    groq_api_key: SecretStr | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_fast_model: str = "openai/gpt-oss-20b"
    groq_answer_model: str = "openai/gpt-oss-120b"
    groq_daily_tokens: int = Field(
        default=170_000, ge=0, description="Per model; kept below the 200K free-tier cap"
    )

    cerebras_api_key: SecretStr | None = None
    cerebras_base_url: str = "https://api.cerebras.ai/v1"
    cerebras_model: str = "gpt-oss-120b"
    cerebras_daily_tokens: int = Field(default=500_000, ge=0)

    local_enabled: bool = False
    local_base_url: str = "http://llm:8080/v1"
    local_model: str = "local"
    local_timeout_seconds: float = Field(default=180.0, gt=0)

    timeout_seconds: float = Field(default=60.0, gt=0)
    visitor_daily_tokens: int = Field(default=20_000, ge=0)
    showcase_reserve: float = Field(default=0.15, ge=0, lt=1)


@lru_cache(maxsize=1)
def get_inference_settings() -> InferenceSettings:
    return InferenceSettings()


def budget_policy(s: InferenceSettings) -> BudgetPolicy:
    return BudgetPolicy(
        daily_tokens={
            f"groq:{s.groq_fast_model}": s.groq_daily_tokens,
            f"groq:{s.groq_answer_model}": s.groq_daily_tokens,
            f"cerebras:{s.cerebras_model}": s.cerebras_daily_tokens,
        },
        visitor_daily_tokens=s.visitor_daily_tokens,
        showcase_reserve=s.showcase_reserve,
    )


def build_chain(
    s: InferenceSettings,
    db: Database | None,
    *,
    role: Role = "answer",
    deterministic: Callable[[ChatRequest], ChatResponse] | None = None,
    client: httpx.Client | None = None,
) -> ProviderChain:
    providers: list[Provider] = [
        OpenAICompatibleProvider(
            name="groq",
            base_url=s.groq_base_url,
            model=s.groq_fast_model if role == "fast" else s.groq_answer_model,
            api_key=s.groq_api_key,
            timeout=s.timeout_seconds,
            client=client,
        ),
    ]
    if s.cerebras_api_key:
        providers.append(
            OpenAICompatibleProvider(
                name="cerebras",
                base_url=s.cerebras_base_url,
                model=s.cerebras_model,
                api_key=s.cerebras_api_key,
                timeout=s.timeout_seconds,
                client=client,
            )
        )
    if s.local_enabled:
        providers.append(
            OpenAICompatibleProvider(
                name="local",
                base_url=s.local_base_url,
                model=s.local_model,
                api_key=None,
                timeout=s.local_timeout_seconds,
                costs_tokens=False,
                require_key=False,
                client=client,
            )
        )
    if deterministic is not None:
        providers.append(DeterministicProvider(deterministic))
    ledger = TokenLedger(db, budget_policy(s)) if db is not None else None
    return ProviderChain(providers, ledger)
