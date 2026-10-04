from __future__ import annotations

import json

from pydantic import BaseModel, Field

from reluai_inference.tools import ToolRegistry
from reluai_inference.types import ToolCall


class MonthArgs(BaseModel):
    month: str = Field(pattern=r"^\d{4}-\d{2}$")


def count_invoices(args: MonthArgs) -> dict[str, int]:
    if args.month == "1999-01":
        raise LookupError("no data before December 2009")
    return {"invoices": 2179}


def registry() -> ToolRegistry:
    r = ToolRegistry()
    r.register("count_invoices", "Count invoices in a month", MonthArgs, count_invoices)
    return r


def call(name: str, arguments: str) -> ToolCall:
    return ToolCall(id="c1", name=name, arguments=arguments)


def test_definition_exposes_json_schema() -> None:
    d = registry().definitions()[0]
    assert d.parameters["properties"]["month"]["pattern"] == r"^\d{4}-\d{2}$"
    assert d.wire()["type"] == "function"


def test_valid_call_executes() -> None:
    out = registry().execute(call("count_invoices", '{"month": "2010-03"}'))
    assert out.ok
    assert json.loads(out.content) == {"ok": True, "result": {"invoices": 2179}}
    assert out.message().role == "tool"
    assert out.message().tool_call_id == "c1"


def test_invalid_arguments_are_returned_to_the_model() -> None:
    out = registry().execute(call("count_invoices", '{"month": "March"}'))
    body = json.loads(out.content)
    assert not out.ok
    assert body["error"] == "arguments failed validation"
    assert body["issues"][0]["field"] == "month"


def test_malformed_json_and_unknown_tool() -> None:
    assert "not valid JSON" in registry().execute(call("count_invoices", "{month:")).content
    unknown = json.loads(registry().execute(call("drop_tables", "{}")).content)
    assert unknown["available"] == ["count_invoices"]


def test_domain_errors_become_tool_errors() -> None:
    out = registry().execute(call("count_invoices", '{"month": "1999-01"}'))
    assert not out.ok and "December 2009" in out.content
