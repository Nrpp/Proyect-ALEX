from __future__ import annotations

import pytest

from alex.plugins.installed.system_exec_plugin import RunShellCommandTool
from alex.tools.base import PermissionLevel

pytestmark = pytest.mark.asyncio


async def test_tool_is_confirm_gated():
    tool = RunShellCommandTool()
    assert tool.permission_level == PermissionLevel.CONFIRM


async def test_successful_command_captures_output():
    tool = RunShellCommandTool()
    result = await tool.run(command="echo hello-alex")
    assert result.success is True
    assert result.data["exit_code"] == 0
    assert "hello-alex" in result.data["stdout"]


async def test_failing_command_reports_nonzero_exit():
    tool = RunShellCommandTool()
    result = await tool.run(command="exit 3")
    assert result.success is False
    assert result.data["exit_code"] == 3


async def test_timeout_kills_process():
    tool = RunShellCommandTool()
    result = await tool.run(command="sleep 5", timeout_seconds=1)
    assert result.success is False
    assert result.data["timed_out"] is True
