"""Provider-neutral chat and tool-calling types (OpenAI-compatible wire format)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ToolDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    description: str
    parameters: dict[str, Any]  # JSON Schema

    def wire(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: str  # raw JSON text as produced by the model — validated before use


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None

    def wire(self) -> dict[str, Any]:
        out: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            out["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": c.arguments},
                }
                for c in self.tool_calls
            ]
        if self.tool_call_id:
            out["tool_call_id"] = self.tool_call_id
        return out


class ChatRequest(BaseModel):
    messages: list[Message]
    tools: list[ToolDefinition] = Field(default_factory=list)
    tool_choice: Literal["auto", "none", "required"] | None = None
    max_tokens: int = Field(default=800, ge=1, le=8192)
    temperature: float = Field(default=0.2, ge=0, le=2)
    json_schema: dict[str, Any] | None = Field(
        default=None, description="Ask for structured output matching this JSON Schema"
    )

    def estimated_tokens(self) -> int:
        """Conservative pre-flight estimate (≈4 characters per token) used for budgeting."""
        chars = sum(len(m.content or "") for m in self.messages)
        chars += sum(len(t.model_dump_json()) for t in self.tools)
        return chars // 4 + self.max_tokens


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


class ChatResponse(BaseModel):
    provider: str
    model: str
    content: str | None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = 0
