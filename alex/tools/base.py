"""
Tool interface and permission levels.

Every capability ALEX can *do* (as opposed to just talk about) is a Tool.
Plugins contribute tools; the Core exposes a fixed set of memory/time tools
built in. The LLM only ever sees `ToolSpec` (name/description/JSON-schema) -
it never touches a Tool object directly, and it can never bypass the
PermissionManager (see permissions.py) - that check happens in
ToolRegistry.execute(), not in the model layer.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from alex.ai.base import ToolSpec


class PermissionLevel(IntEnum):
    """Ordered so comparisons like `level >= PermissionLevel.CONFIRM` work."""

    READ = 0       # read-only, no side effects (query memory, get time/system status)
    WRITE = 1      # local side effects that are easy to undo (save a memory, set a reminder)
    CONFIRM = 2    # side effects that need explicit user go-ahead (send a message, delete data)
    BLOCKED = 3    # never executable by the LLM, present only for documentation/future use


@dataclass
class ToolResult:
    success: bool
    content: str  # human/LLM-readable summary, fed back into the conversation
    data: dict[str, Any] = field(default_factory=dict)


class Tool(ABC):
    name: str
    description: str
    permission_level: PermissionLevel = PermissionLevel.READ
    parameters: dict[str, Any] = {"type": "object", "properties": {}, "required": []}

    @abstractmethod
    async def run(self, **kwargs) -> ToolResult:
        raise NotImplementedError

    def spec(self) -> ToolSpec:
        return ToolSpec(name=self.name, description=self.description, parameters=self.parameters)
