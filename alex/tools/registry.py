"""ToolRegistry - where plugins and builtins register tools, and the only place that runs them."""
from __future__ import annotations

import logging

from alex.ai.base import ToolSpec
from alex.core.errors import ConfirmationRequired, PermissionDenied, ToolError
from alex.tools.base import Tool, ToolResult
from alex.tools.permissions import PermissionManager

log = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self, permission_manager: PermissionManager):
        self._tools: dict[str, Tool] = {}
        self._permissions = permission_manager

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            log.warning("Tool '%s' registered twice - overwriting", tool.name)
        self._tools[tool.name] = tool
        log.info("Registered tool '%s' (level=%s)", tool.name, tool.permission_level.name)

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def specs(self) -> list[ToolSpec]:
        return [t.spec() for t in self._tools.values()]

    def names(self) -> list[str]:
        return list(self._tools.keys())

    async def execute(self, name: str, arguments: dict) -> ToolResult:
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"Herramienta desconocida: '{name}'")

        # This call is what makes the permission system unbypassable: it may
        # raise PermissionDenied or ConfirmationRequired, in which case the
        # tool body below never executes.
        await self._permissions.authorize(tool, arguments)

        try:
            return await tool.run(**arguments)
        except (PermissionDenied, ConfirmationRequired):
            raise
        except TypeError as e:
            raise ToolError(f"Argumentos invalidos para '{name}': {e}") from e
        except Exception as e:
            log.exception("Tool '%s' raised an exception", name)
            raise ToolError(f"Fallo al ejecutar '{name}': {e}") from e

    async def execute_confirmed(self, name: str, arguments: dict) -> ToolResult:
        """Runs a tool that already passed a CONFIRM gate - skips authorize()."""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolError(f"Herramienta desconocida: '{name}'")
        try:
            return await tool.run(**arguments)
        except Exception as e:
            log.exception("Confirmed tool '%s' raised an exception", name)
            raise ToolError(f"Fallo al ejecutar '{name}': {e}") from e
