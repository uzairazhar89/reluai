"""Providers: any OpenAI-compatible endpoint (Groq, Cerebras, llama.cpp) or a deterministic
function. Tool definitions and messages use one format for all of them."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx
from pydantic import SecretStr

from reluai_inference.errors import (
    BadRequestError,
    NotConfiguredError,
    ProviderUnavailableError,
    RateLimitedError,
)
from reluai_inference.types import ChatRequest, ChatResponse, ToolCall, Usage


class Provider(Protocol):
    name: str
    model: str
    costs_tokens: bool  # whether usage counts against an external quota

    def available(self) -> bool: ...

    def chat(self, request: ChatRequest) -> ChatResponse: ...


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        model: str,
        api_key: SecretStr | None,
        timeout: float = 60.0,
        costs_tokens: bool = True,
        require_key: bool = True,
        client: httpx.Client | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.costs_tokens = costs_tokens
        self.require_key = require_key
        self._client = client or httpx.Client(timeout=timeout)

    def available(self) -> bool:
        return bool(self.api_key and self.api_key.get_secret_value()) or not self.require_key

    def _payload(self, request: ChatRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [m.wire() for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
        }
        if request.tools:
            payload["tools"] = [t.wire() for t in request.tools]
            if request.tool_choice:
                payload["tool_choice"] = request.tool_choice
        if request.json_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "result", "schema": request.json_schema},
            }
        return payload

    def chat(self, request: ChatRequest) -> ChatResponse:
        if not self.available():
            raise NotConfiguredError(f"{self.name}: no API key configured")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key.get_secret_value()}"
        t0 = time.perf_counter()
        try:
            resp = self._client.post(
                f"{self.base_url}/chat/completions", json=self._payload(request), headers=headers
            )
        except httpx.TimeoutException as exc:
            raise ProviderUnavailableError(f"{self.name}: timeout") from exc
        except httpx.TransportError as exc:
            raise ProviderUnavailableError(f"{self.name}: {type(exc).__name__}") from exc
        latency = round((time.perf_counter() - t0) * 1000)

        if resp.status_code == 429:
            retry = resp.headers.get("retry-after")
            raise RateLimitedError(
                f"{self.name}: rate limited",
                retry_after=float(retry) if retry and retry.replace(".", "", 1).isdigit() else None,
            )
        if resp.status_code in (401, 403):
            raise NotConfiguredError(f"{self.name}: credentials rejected ({resp.status_code})")
        if resp.status_code in (400, 404, 413, 422):
            raise BadRequestError(f"{self.name}: request rejected ({resp.status_code})")
        if resp.status_code >= 500:
            raise ProviderUnavailableError(f"{self.name}: upstream {resp.status_code}")
        resp.raise_for_status()

        body = resp.json()
        try:
            choice = body["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderUnavailableError(f"{self.name}: malformed response") from exc
        calls = [
            ToolCall(
                id=str(c.get("id", f"call_{i}")),
                name=c["function"]["name"],
                arguments=c["function"].get("arguments") or "{}",
            )
            for i, c in enumerate(message.get("tool_calls") or [])
        ]
        usage = body.get("usage") or {}
        return ChatResponse(
            provider=self.name,
            model=str(body.get("model", self.model)),
            content=message.get("content"),
            tool_calls=calls,
            finish_reason=choice.get("finish_reason"),
            usage=Usage(
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
            ),
            latency_ms=latency,
        )


class DeterministicProvider:
    """Wraps a feature-specific rule-based handler: always available, zero tokens."""

    costs_tokens = False

    def __init__(
        self,
        handler: Callable[[ChatRequest], ChatResponse],
        *,
        name: str = "deterministic",
        model: str = "rules",
    ) -> None:
        self.name = name
        self.model = model
        self._handler = handler

    def available(self) -> bool:
        return True

    def chat(self, request: ChatRequest) -> ChatResponse:
        t0 = time.perf_counter()
        resp = self._handler(request)
        return resp.model_copy(
            update={
                "provider": self.name,
                "model": self.model,
                "latency_ms": round((time.perf_counter() - t0) * 1000),
            }
        )
