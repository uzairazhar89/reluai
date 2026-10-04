from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from reluai_inference.chain import ProviderChain
from reluai_inference.errors import AllProvidersFailedError, BadRequestError
from reluai_inference.providers import DeterministicProvider, OpenAICompatibleProvider
from reluai_inference.types import ChatRequest, ChatResponse, Message, ToolDefinition

REQ = ChatRequest(
    messages=[Message(role="user", content="How many invoices in March 2010?")],
    tools=[
        ToolDefinition(
            name="count_invoices",
            description="Count invoices in a month",
            parameters={
                "type": "object",
                "properties": {"month": {"type": "string"}},
                "required": ["month"],
            },
        )
    ],
    tool_choice="auto",
)


def ok_body(**message: Any) -> dict[str, Any]:
    return {
        "model": "openai/gpt-oss-120b",
        "choices": [{"message": {"role": "assistant", **message}, "finish_reason": "tool_calls"}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30},
    }


def provider(handler: Any, name: str = "groq", key: str | None = "k") -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        name=name,
        base_url="https://llm.test/v1",
        model="openai/gpt-oss-120b",
        api_key=SecretStr(key) if key else None,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_payload_uses_openai_tool_format_and_parses_tool_calls() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(
            200,
            json=ok_body(
                content=None,
                tool_calls=[
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "count_invoices", "arguments": '{"month": "2010-03"}'},
                    }
                ],
            ),
        )

    resp = provider(handler).chat(REQ)
    assert seen["tools"][0]["type"] == "function"
    assert seen["tools"][0]["function"]["name"] == "count_invoices"
    assert seen["tool_choice"] == "auto"
    assert seen["auth"] == "Bearer k"
    assert resp.tool_calls[0].name == "count_invoices"
    assert json.loads(resp.tool_calls[0].arguments) == {"month": "2010-03"}
    assert resp.usage.total == 150


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (429, "rate_limited"),
        (401, "not_configured"),
        (503, "unavailable"),
    ],
)
def test_errors_fall_through_to_next_provider(status: int, outcome: str) -> None:
    failing = provider(lambda r: httpx.Response(status, headers={"retry-after": "3"}))
    backup = provider(lambda r: httpx.Response(200, json=ok_body(content="42")), name="local")
    result = ProviderChain([failing, backup]).complete(REQ, feature="test")
    assert result.response.content == "42"
    assert result.response.provider == "local"
    assert [a.outcome for a in result.attempts] == [outcome, "ok"]
    assert result.fell_back


def test_timeouts_are_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    det = DeterministicProvider(lambda r: ChatResponse(provider="", model="", content="rules"))
    result = ProviderChain([provider(handler), det]).complete(REQ, feature="test")
    assert result.attempts[0].outcome == "unavailable"
    assert result.response.provider == "deterministic"
    assert result.response.usage.total == 0


def test_bad_request_does_not_fall_through() -> None:
    bad = provider(lambda r: httpx.Response(400))
    det = DeterministicProvider(lambda r: ChatResponse(provider="", model="", content="x"))
    with pytest.raises(BadRequestError):
        ProviderChain([bad, det]).complete(REQ, feature="test")


def test_unconfigured_provider_is_skipped_without_a_request() -> None:
    calls = []
    p = provider(
        lambda r: calls.append(r) or httpx.Response(200, json=ok_body(content="x")), key=None
    )
    det = DeterministicProvider(lambda r: ChatResponse(provider="", model="", content="y"))
    result = ProviderChain([p, det]).complete(REQ, feature="test")
    assert calls == []
    assert result.attempts[0].outcome == "not_configured"


def test_all_failed_raises_with_attempts() -> None:
    p = provider(lambda r: httpx.Response(503))
    with pytest.raises(AllProvidersFailedError) as err:
        ProviderChain([p]).complete(REQ, feature="test")
    assert len(err.value.attempts) == 1


def test_structured_output_requested_as_json_schema() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=ok_body(content='{"a": 1}'))

    req = REQ.model_copy(update={"json_schema": {"type": "object"}, "tools": []})
    provider(handler).chat(req)
    assert seen["response_format"]["type"] == "json_schema"
    assert "tools" not in seen
