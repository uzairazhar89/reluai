"""LLM fallback: one tool call that fills in the query plan (function calling, step 1).

Used only when the rule-based parser declines. The model sees the table's column list and
two tools: ``run_query_plan`` (arguments = the plan's JSON Schema) and ``cannot_answer``.
Its arguments are parsed with Pydantic and checked by the same validator as the rules; if
anything is wrong, the problems are sent back as the tool result and the model gets up to
``llm_max_retries`` more attempts. The plan is still only data: it is compiled to
parameterised SQL by our code, never executed as written.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field

from pydantic import ValidationError

from reluai_core.logging import get_logger
from reluai_csv.plan import QueryPlan, Refusal, plan_json_schema
from reluai_csv.schema import DatasetSchema
from reluai_csv.validate import Issue, validate_plan
from reluai_inference.chain import Attempt, ProviderChain
from reluai_inference.errors import AllProvidersFailedError
from reluai_inference.types import ChatRequest, Message, ToolDefinition

log = get_logger(__name__)
FEATURE = "csv.plan"

PLAN_TOOL = ToolDefinition(
    name="run_query_plan",
    description=(
        "Answer the question with an aggregate query over the table. Use only listed "
        "columns. Dates as YYYY, YYYY-MM or YYYY-MM-DD."
    ),
    parameters=plan_json_schema(),
)
REFUSE_TOOL = ToolDefinition(
    name="cannot_answer",
    description=(
        "Use when the table cannot answer the question: it asks why something happened, "
        "for a prediction or opinion, for data that is not in the columns, or for "
        "individual rows rather than totals."
    ),
    parameters={
        "type": "object",
        "properties": {"reason": {"type": "string", "minLength": 3, "maxLength": 300}},
        "required": ["reason"],
        "additionalProperties": False,
    },
)


@dataclass(slots=True)
class LlmPlanResult:
    plan: QueryPlan | None = None
    refusal: str | None = None
    provider: str | None = None
    model: str | None = None
    retries: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    attempts: list[Attempt] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    unavailable: bool = False

    @property
    def tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def describe_table(schema: DatasetSchema, *, rows: int, include_values: bool) -> str:
    lines = [f'Table "{schema.table}" ({rows:,} rows). Columns:']
    for c in schema.columns:
        line = f"- {c.name} ({c.kind})"
        if c.description:
            line += f": {c.description}"
        if include_values and c.values:
            sample = ", ".join(c.values[:12])
            more = f" (+{len(c.values) - 12} more)" if len(c.values) > 12 else ""
            line += f" Values: {sample}{more}."
        lines.append(line)
    if schema.default_date:
        lines.append(f"Use {schema.default_date} for dates and time groupings.")
    return "\n".join(lines)


SYSTEM_PROMPT = """\
You turn a question about one table into a query plan. Respond only by calling exactly one
tool: run_query_plan with a plan that answers the question, or cannot_answer when the table
cannot. Plans are aggregate queries: metrics (count, count_distinct, sum, avg, min, max),
optional group_by (category columns), optional time_bucket (a date column and a grain),
filters, sort and limit. Use only the columns listed below, spelled exactly. Category
filter values must match the listed values. Do not invent columns, values or tables.

{table}"""


def _issues_from_validation(exc: ValidationError) -> list[Issue]:
    return [
        Issue(".".join(str(p) for p in e["loc"]) or "plan", "schema", str(e["msg"]))
        for e in exc.errors()
    ][:12]


def plan_with_llm(
    question: str,
    schema: DatasetSchema,
    *,
    rows: int,
    include_values: bool,
    chain_factory: Callable[[], ProviderChain],
    visitor: str | None,
    max_retries: int,
) -> LlmPlanResult:
    result = LlmPlanResult()
    try:
        chain = chain_factory()
    except Exception:
        log.exception("csv.llm_chain_failed")
        result.unavailable = True
        return result
    system = SYSTEM_PROMPT.format(
        table=describe_table(schema, rows=rows, include_values=include_values)
    )
    messages = [Message(role="system", content=system), Message(role="user", content=question)]
    for attempt in range(max_retries + 1):
        request = ChatRequest(
            messages=messages,
            tools=[PLAN_TOOL, REFUSE_TOOL],
            tool_choice="required",
            max_tokens=700,
            temperature=0,
        )
        try:
            chained = chain.complete(request, feature=FEATURE, visitor=visitor)
        except AllProvidersFailedError as exc:
            result.attempts.extend(a for a in exc.attempts if isinstance(a, Attempt))
            result.unavailable = True
            return result
        response = chained.response
        result.attempts.extend(chained.attempts)
        result.provider, result.model = response.provider, response.model
        result.prompt_tokens += response.usage.prompt_tokens
        result.completion_tokens += response.usage.completion_tokens
        result.latency_ms += response.latency_ms
        result.retries = attempt

        call = response.tool_calls[0] if response.tool_calls else None
        if call is None:
            issues = [Issue("tool", "no_tool_call", "Respond by calling one of the two tools.")]
            messages = [
                *messages,
                Message(role="assistant", content=response.content or ""),
                Message(role="user", content=issues[0].message),
            ]
            result.issues = issues
            _log_retry(attempt, issues, response.provider)
            continue
        if call.name == REFUSE_TOOL.name:
            try:
                result.refusal = Refusal.model_validate_json(call.arguments).reason
            except ValidationError:
                result.refusal = "The question cannot be answered from this table."
            return result
        issues: list[Issue]  # type: ignore[no-redef]
        if call.name != PLAN_TOOL.name:
            issues = [Issue("tool", "unknown_tool", f"There is no tool named '{call.name}'.")]
        else:
            try:
                candidate = QueryPlan.model_validate_json(call.arguments or "{}")
            except ValidationError as exc:
                issues = _issues_from_validation(exc)
            else:
                checked = validate_plan(candidate, schema)
                if checked.ok and checked.plan is not None:
                    result.plan = checked.plan
                    result.issues = []
                    return result
                issues = checked.issues
        result.issues = issues
        _log_retry(attempt, issues, response.provider)
        messages = [
            *messages,
            Message(role="assistant", content=None, tool_calls=[call]),
            Message(
                role="tool",
                tool_call_id=call.id,
                content=json.dumps(
                    {"ok": False, "errors": [i.as_dict() for i in issues]}, ensure_ascii=False
                ),
            ),
        ]
    return result


def _log_retry(attempt: int, issues: list[Issue], provider: str | None) -> None:
    log.info(
        "csv.plan_rejected",
        attempt=attempt + 1,
        provider=provider,
        codes=sorted({i.code for i in issues}),
    )
