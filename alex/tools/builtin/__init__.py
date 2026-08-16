"""Builtin tools that always exist regardless of which plugins are enabled."""
from __future__ import annotations

from alex.config import Settings
from alex.memory.manager import MemoryManager
from alex.notifications.manager import NotificationManager
from alex.tools.base import Tool
from alex.tools.builtin.memory_tools import (
    ForgetMemoryTool,
    RecallMemoryTool,
    RememberTool,
    SetFactTool,
    SetPreferenceTool,
)
from alex.tools.builtin.notification_tools import SendNotificationTool
from alex.tools.builtin.time_tools import GetCurrentTimeTool


def get_builtin_tools(memory: MemoryManager, settings: Settings, notifications: NotificationManager) -> list[Tool]:
    return [
        RememberTool(memory),
        RecallMemoryTool(memory),
        ForgetMemoryTool(memory),
        SetFactTool(memory),
        SetPreferenceTool(memory),
        GetCurrentTimeTool(settings),
        SendNotificationTool(notifications),
    ]
