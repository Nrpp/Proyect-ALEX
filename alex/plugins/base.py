"""
Plugin interface.

A plugin is how ALEX gains a new integration (Microsoft To Do, calendar,
email, Home Assistant, system info, reminders, ...) WITHOUT the Core ever
being modified. A plugin can:

  - contribute Tools (via ctx.register_tool)
  - listen to / publish internal events (via ctx.event_bus, ctx.emit_event)
  - run background work on a schedule (via ctx.schedule_interval)
  - read its own config section (via ctx.plugin_config)
  - use memory (via ctx.memory) - never raw SQL, same rule as everything else

Authentication for integrations that need it (OAuth tokens, API keys) is the
plugin's own responsibility: read credentials from `ctx.plugin_config` /
environment, store refreshed tokens via `ctx.memory.set_preference` (or a
dedicated per-plugin table added by that plugin if it truly needs one). This
keeps the Core free of any integration-specific auth logic.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from alex.core.event_bus import EventBus
from alex.memory.manager import MemoryManager
from alex.tools.base import Tool


@dataclass
class PluginContext:
    event_bus: EventBus
    memory: MemoryManager
    register_tool: Callable[[Tool], None]
    emit_event: Callable[..., Awaitable[None]]
    schedule_interval: Callable[[Callable[[], Awaitable[None]], float, str], None]
    plugin_config: dict[str, Any]


class Plugin(ABC):
    id: str
    name: str
    version: str = "0.1.0"

    @abstractmethod
    async def setup(self, ctx: PluginContext) -> None:
        """Called once at startup. Register tools / event handlers / scheduled jobs here."""
        raise NotImplementedError

    async def shutdown(self) -> None:
        """Optional cleanup hook, called during graceful shutdown."""
        return None
