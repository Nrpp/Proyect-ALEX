"""Builtin tools that always exist regardless of which plugins are enabled."""
from __future__ import annotations

from alex.config import Settings
from alex.memory.manager import MemoryManager
from alex.tools.base import Tool
from alex.tools.builtin.memory_tools import (
    ForgetMemoryTool,
    RecallMemoryTool,
    RememberTool,
    SetFactTool,
    SetPreferenceTool,
)
from alex.tools.builtin.time_tools import GetCurrentTimeTool


def get_builtin_tools(memory: MemoryManager, settings: Settings) -> list[Tool]:
    return [
        RememberTool(memory),
        RecallMemoryTool(memory),
        ForgetMemoryTool(memory),
        SetFactTool(memory),
        SetPreferenceTool(memory),
        GetCurrentTimeTool(settings),
    ]
