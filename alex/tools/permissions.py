"""
PermissionManager - the single gatekeeper between the LLM's intentions and
real side effects.

`ToolRegistry.execute()` always calls `PermissionManager.authorize()` before
running a tool. There is no other path to run a tool, so the model can never
skip this check:

  READ / WRITE  -> authorized immediately, tool runs.
  CONFIRM       -> a PendingAction is created and ConfirmationRequired is
                    raised; the Core turns that into a question/notification
                    to the user instead of executing anything. The tool only
                    actually runs once something calls `resolve()` with
                    approved=True (wired to the WebSocket/REST confirm
                    endpoint in alex/server).
  BLOCKED       -> PermissionDenied, always, no exceptions.

Additionally, `blocked_tools` from config lets the owner hard-block any tool
by name regardless of its declared level (defense in depth / kill switch).
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from alex.core.errors import ConfirmationRequired, PermissionDenied
from alex.tools.base import PermissionLevel, Tool

log = logging.getLogger(__name__)


@dataclass
class PendingAction:
    id: str
    tool_name: str
    arguments: dict[str, Any]
    reason: str
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class PermissionManager:
    def __init__(self, blocked_tools: list[str] | None = None):
        self._blocked_tools = set(blocked_tools or [])
        self._pending: dict[str, PendingAction] = {}

    def block_tool(self, tool_name: str) -> None:
        self._blocked_tools.add(tool_name)

    def unblock_tool(self, tool_name: str) -> None:
        self._blocked_tools.discard(tool_name)

    async def authorize(self, tool: Tool, arguments: dict[str, Any]) -> None:
        """Raises PermissionDenied or ConfirmationRequired; returns normally if OK to run now."""
        if tool.name in self._blocked_tools or tool.permission_level == PermissionLevel.BLOCKED:
            log.warning("Blocked tool call attempted: %s", tool.name)
            raise PermissionDenied(f"La herramienta '{tool.name}' esta bloqueada.")

        if tool.permission_level == PermissionLevel.CONFIRM:
            action = self._create_pending(tool.name, arguments, tool.description)
            raise ConfirmationRequired(
                f"'{tool.name}' requiere confirmacion antes de ejecutarse.", action_id=action.id
            )

        # READ / WRITE: authorized to run immediately.
        return None

    def _create_pending(self, tool_name: str, arguments: dict[str, Any], reason: str) -> PendingAction:
        action = PendingAction(id=str(uuid.uuid4()), tool_name=tool_name, arguments=arguments, reason=reason)
        self._pending[action.id] = action
        log.info("Pending confirmation created: %s -> %s(%s)", action.id, tool_name, arguments)
        return action

    def get_pending(self, action_id: str) -> PendingAction | None:
        return self._pending.get(action_id)

    def list_pending(self) -> list[PendingAction]:
        return list(self._pending.values())

    def pop_pending(self, action_id: str) -> PendingAction | None:
        return self._pending.pop(action_id, None)
