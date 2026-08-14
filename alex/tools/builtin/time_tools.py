from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from alex.config import Settings
from alex.tools.base import PermissionLevel, Tool, ToolResult


class GetCurrentTimeTool(Tool):
    name = "get_current_time"
    description = "Devuelve la fecha y hora actuales en la zona horaria del usuario."
    permission_level = PermissionLevel.READ
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, settings: Settings):
        self._tz = ZoneInfo(settings.timezone)

    async def run(self) -> ToolResult:
        now = datetime.now(self._tz)
        text = now.strftime("%A %d de %B de %Y, %H:%M")
        return ToolResult(success=True, content=text, data={"iso": now.isoformat()})
