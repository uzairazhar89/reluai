"""Tool registry for function calling.

Tools are ordinary, tested Python functions with a Pydantic argument model. The model only
*proposes* a call; arguments are parsed and validated before the function runs, and
validation errors are returned to the model as data so it can correct itself. Nothing the
model writes is ever executed as code.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from reluai_inference.types import Message, ToolCall, ToolDefinition


@dataclass(frozen=True, slots=True)
class Tool:
    name: str
    description: str
    args_model: type[BaseModel]
    fn: Callable[[Any], Any]

    def definition(self) -> ToolDefinition:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return ToolDefinition(name=self.name, description=self.description, parameters=schema)


@dataclass(frozen=True, slots=True)
class ToolOutcome:
    call: ToolCall
    ok: bool
    content: str  # JSON text returned to the model

    def message(self) -> Message:
        return Message(role="tool", tool_call_id=self.call.id, content=self.content)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(
        self, name: str, description: str, args_model: type[BaseModel], fn: Callable[[Any], Any]
    ) -> None:
        if name in self._tools:
            raise ValueError(f"tool {name!r} already registered")
        self._tools[name] = Tool(name, description, args_model, fn)

    def definitions(self) -> list[ToolDefinition]:
        return [t.definition() for t in self._tools.values()]

    def execute(self, call: ToolCall) -> ToolOutcome:
        tool = self._tools.get(call.name)
        if tool is None:
            return self._error(
                call, f"unknown tool '{call.name}'", {"available": sorted(self._tools)}
            )
        try:
            raw = json.loads(call.arguments or "{}")
        except json.JSONDecodeError as exc:
            return self._error(call, f"arguments are not valid JSON: {exc.msg}")
        try:
            args = tool.args_model.model_validate(raw)
        except ValidationError as exc:
            issues = [
                {"field": ".".join(str(p) for p in e["loc"]), "problem": e["msg"]}
                for e in exc.errors()
            ]
            return self._error(call, "arguments failed validation", {"issues": issues})
        try:
            result = tool.fn(args)
        except (LookupError, ValueError) as exc:  # domain errors are reported, not raised
            return self._error(call, str(exc))
        payload = result.model_dump(mode="json") if isinstance(result, BaseModel) else result
        return ToolOutcome(
            call=call, ok=True, content=json.dumps({"ok": True, "result": payload}, default=str)
        )

    @staticmethod
    def _error(call: ToolCall, message: str, extra: dict[str, Any] | None = None) -> ToolOutcome:
        body: dict[str, Any] = {"ok": False, "error": message}
        if extra:
            body.update(extra)
        return ToolOutcome(call=call, ok=False, content=json.dumps(body))
