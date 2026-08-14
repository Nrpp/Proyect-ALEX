from __future__ import annotations

import pytest

from alex.core.errors import ConfirmationRequired, PermissionDenied
from alex.tools.base import PermissionLevel, Tool, ToolResult
from alex.tools.permissions import PermissionManager
from alex.tools.registry import ToolRegistry

pytestmark = pytest.mark.asyncio


class ReadTool(Tool):
    name = "read_tool"
    description = "read"
    permission_level = PermissionLevel.READ

    async def run(self) -> ToolResult:
        return ToolResult(success=True, content="read ok")


class WriteTool(Tool):
    name = "write_tool"
    description = "write"
    permission_level = PermissionLevel.WRITE

    async def run(self) -> ToolResult:
        return ToolResult(success=True, content="write ok")


class ConfirmTool(Tool):
    name = "confirm_tool"
    description = "dangerous"
    permission_level = PermissionLevel.CONFIRM

    async def run(self) -> ToolResult:
        return ToolResult(success=True, content="confirmed action executed")


class BlockedTool(Tool):
    name = "blocked_tool"
    description = "blocked"
    permission_level = PermissionLevel.BLOCKED

    async def run(self) -> ToolResult:
        return ToolResult(success=True, content="should never run")


async def test_read_and_write_run_immediately():
    registry = ToolRegistry(PermissionManager())
    registry.register(ReadTool())
    registry.register(WriteTool())

    assert (await registry.execute("read_tool", {})).content == "read ok"
    assert (await registry.execute("write_tool", {})).content == "write ok"


async def test_blocked_tool_is_never_executed():
    registry = ToolRegistry(PermissionManager())
    registry.register(BlockedTool())

    with pytest.raises(PermissionDenied):
        await registry.execute("blocked_tool", {})


async def test_confirm_tool_requires_confirmation_then_executes():
    perms = PermissionManager()
    registry = ToolRegistry(perms)
    registry.register(ConfirmTool())

    with pytest.raises(ConfirmationRequired) as exc_info:
        await registry.execute("confirm_tool", {})

    action_id = exc_info.value.action_id
    pending = perms.get_pending(action_id)
    assert pending is not None
    assert pending.tool_name == "confirm_tool"

    # The LLM can never run it directly - only execute_confirmed (used after
    # the user approves via the API) actually runs the tool body.
    action = perms.pop_pending(action_id)
    result = await registry.execute_confirmed(action.tool_name, action.arguments)
    assert result.content == "confirmed action executed"


async def test_hard_blocklist_overrides_declared_level():
    perms = PermissionManager(blocked_tools=["write_tool"])
    registry = ToolRegistry(perms)
    registry.register(WriteTool())

    with pytest.raises(PermissionDenied):
        await registry.execute("write_tool", {})
