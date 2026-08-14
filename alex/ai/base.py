"""
Provider-agnostic AI interface.

This is the seam that keeps ALEX from being locked to any single model
vendor. Every provider (NVIDIA NIM today, Anthropic Claude today, anything
else tomorrow) implements `AIProvider.complete()` and speaks in these plain
dataclasses. Nothing else in ALEX imports `openai` or `anthropic` directly -
only the two files in this package do.

Swapping the active provider is a config change (`ALEX_AI_PROVIDER=...`),
never a code change in Core, Memory, Tools or Plugins.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

Role = Literal["system", "user", "assistant", "tool"]


@dataclass
class ChatMessage:
    role: Role
    content: str
    # Only used for role="tool" messages: which tool call this answers.
    tool_call_id: str | None = None
    # Only used for role="assistant" messages that requested tools.
    tool_calls: list["ToolCall"] | None = None
    name: str | None = None  # tool name, set on role="tool" messages


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolSpec:
    """JSON-schema tool description, translated per-provider at call time."""
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema for the "properties" object


@dataclass
class AIResponse:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    raw_usage: dict[str, int] | None = None

    @property
    def wants_tool_call(self) -> bool:
        return bool(self.tool_calls)


class AIProvider(ABC):
    """Implemented once per model vendor. See nvidia_provider.py / anthropic_provider.py."""

    name: str = "base"

    @abstractmethod
    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        system: str,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.4,
    ) -> AIResponse:
        """Run one model turn. May return tool_calls instead of final content."""
        raise NotImplementedError

    @abstractmethod
    async def health_check(self) -> bool:
        raise NotImplementedError
