"""The LLM fallback, with scripted providers standing in for a model.

No network: each test gives the chain a deterministic provider that replays tool calls,
including invalid ones, to exercise validation, retries, refusals and outages.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from reluai_csv.llm import PLAN_TOOL, REFUSE_TOOL, LlmPlanResult, plan_with_llm
from reluai_csv.schema import DatasetSchema
from reluai_inference.chain import ProviderChain
from reluai_inference.providers import DeterministicProvider
from reluai_inference.types import ChatRequest, ChatResponse, ToolCall, Usage

Script = list[tuple[str, dict[str, Any]] | None]


class Recorder:
    def __init__(self, script: Script) -> None:
        self.script = list(script)
        self.requests: list[ChatRequest] = []

    def __call__(self, request: ChatRequest) -> ChatResponse:
        self.requests.append(request)
        step = self.script.pop(0)
        if step is None:
            return ChatResponse(provider="", model="", content="I think it is 42.")
        name, args = step
        return ChatResponse(
            provider="",
            model="",
            content=None,
            tool_calls=[
                ToolCall(id=f"call_{len(self.requests)}", name=name, arguments=json.dumps(args))
            ],
            usage=Usage(prompt_tokens=100, completion_tokens=20),
        )


def factory(recorder: Recorder) -> Callable[[], ProviderChain]:
    return lambda: ProviderChain([DeterministicProvider(recorder, name="scripted", model="fake")])


def ask(
    schema: DatasetSchema, recorder: Recorder, *, retries: int = 2, values: bool = True
) -> LlmPlanResult:
    return plan_with_llm(
        "What did German customers spend each year?",
        schema,
        rows=1000,
        include_values=values,
        chain_factory=factory(recorder),
        visitor="v",
        max_retries=retries,
    )


GOOD = {
    "metrics": [{"agg": "sum", "column": "revenue"}],
    "time_bucket": {"column": "invoiced_at", "grain": "year"},
    "filters": [{"column": "country", "op": "eq", "value": "germany"}],
    "sort": "group_asc",
}


def test_valid_plan_on_first_call(schema: DatasetSchema) -> None:
    rec = Recorder([(PLAN_TOOL.name, GOOD)])
    result = ask(schema, rec)
    assert result.plan is not None
    assert result.plan.filters[0].value == "Germany"  # normalised by the validator
    assert result.retries == 0
    assert result.provider == "scripted"
    assert result.tokens == 120
    request = rec.requests[0]
    assert request.tool_choice == "required"
    assert {t.name for t in request.tools} == {PLAN_TOOL.name, REFUSE_TOOL.name}
    assert request.temperature == 0


def test_invalid_plan_is_sent_back_and_corrected(schema: DatasetSchema) -> None:
    wrong = {**GOOD, "metrics": [{"agg": "sum", "column": "sales_amount"}]}
    rec = Recorder([(PLAN_TOOL.name, wrong), (PLAN_TOOL.name, GOOD)])
    result = ask(schema, rec)
    assert result.plan is not None
    assert result.retries == 1
    feedback = rec.requests[1].messages[-1]
    assert feedback.role == "tool"
    body = json.loads(feedback.content or "{}")
    assert body["ok"] is False
    assert body["errors"][0]["code"] == "unknown_column"
    assert "revenue" in body["errors"][0]["message"]  # the hint names the real column


def test_schema_errors_are_retried(schema: DatasetSchema) -> None:
    rec = Recorder(
        [
            (PLAN_TOOL.name, {"metrics": [], "sql": "SELECT 1"}),
            (PLAN_TOOL.name, {**GOOD, "limit": 5000}),
            (PLAN_TOOL.name, GOOD),
        ]
    )
    result = ask(schema, rec)
    assert result.plan is not None
    assert result.retries == 2


def test_gives_up_after_the_retry_budget(schema: DatasetSchema) -> None:
    bad = (PLAN_TOOL.name, {"metrics": [{"agg": "sum", "column": "country"}]})
    rec = Recorder([bad, bad, bad, bad])
    result = ask(schema, rec, retries=2)
    assert result.plan is None
    assert len(rec.requests) == 3
    assert [i.code for i in result.issues] == ["type_mismatch"]


def test_refusal(schema: DatasetSchema) -> None:
    rec = Recorder([(REFUSE_TOOL.name, {"reason": "The table has no profit column."})])
    result = ask(schema, rec)
    assert result.plan is None
    assert result.refusal == "The table has no profit column."


def test_text_answer_without_a_tool_call_is_not_trusted(schema: DatasetSchema) -> None:
    rec = Recorder([None, (PLAN_TOOL.name, GOOD)])
    result = ask(schema, rec)
    assert result.plan is not None
    assert rec.requests[1].messages[-1].role == "user"


def test_unknown_tool_name(schema: DatasetSchema) -> None:
    rec = Recorder([("run_sql", {"sql": "DROP TABLE sales"}), (PLAN_TOOL.name, GOOD)])
    result = ask(schema, rec)
    assert result.plan is not None
    assert "run_sql" in (rec.requests[1].messages[-1].content or "")


def test_no_provider_available(schema: DatasetSchema) -> None:
    class Offline:
        name, model, costs_tokens = "groq", "m", True

        def available(self) -> bool:
            return False

        def chat(self, request: ChatRequest) -> ChatResponse:  # pragma: no cover
            raise AssertionError

    result = plan_with_llm(
        "anything",
        schema,
        rows=1,
        include_values=True,
        chain_factory=lambda: ProviderChain([Offline()]),
        visitor=None,
        max_retries=2,
    )
    assert result.unavailable
    assert result.plan is None
    assert [a.outcome for a in result.attempts] == ["not_configured"]


def test_chain_factory_failure_is_unavailable(schema: DatasetSchema) -> None:
    def broken() -> ProviderChain:
        raise RuntimeError("misconfigured")

    result = plan_with_llm(
        "anything",
        schema,
        rows=1,
        include_values=True,
        chain_factory=broken,
        visitor=None,
        max_retries=0,
    )
    assert result.unavailable


def test_upload_prompts_carry_column_names_not_values(schema: DatasetSchema) -> None:
    rec = Recorder([(PLAN_TOOL.name, GOOD)])
    ask(schema, rec, values=False)
    system = rec.requests[0].messages[0].content or ""
    assert "country (text)" in system
    assert "United Kingdom" not in system
    rec = Recorder([(PLAN_TOOL.name, GOOD)])
    ask(schema, rec, values=True)
    assert "United Kingdom" in (rec.requests[0].messages[0].content or "")
