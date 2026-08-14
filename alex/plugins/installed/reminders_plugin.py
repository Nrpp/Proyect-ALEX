"""
Reminders plugin - the reference example of a plugin that closes the full
loop: tool call -> memory write -> scheduled background check -> event ->
notification/voice announcement.

Reminders are stored via MemoryManager (never raw SQL from the plugin).
Due times are ISO-8601 local timestamps without a UTC offset, e.g.
"2026-08-20T09:00:00", interpreted in ALEX's configured timezone
(ALEX_TIMEZONE) - keep it simple and consistent since everything runs on a
single Pi in a single timezone.
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from alex.config import get_settings
from alex.events.models import Event
from alex.plugins.base import Plugin, PluginContext
from alex.tools.base import PermissionLevel, Tool, ToolResult

log = logging.getLogger(__name__)


class SetReminderTool(Tool):
    name = "set_reminder"
    description = (
        "Crea un recordatorio que avisara al usuario en una fecha/hora concreta. "
        "Usa get_current_time primero si necesitas calcular una hora relativa (ej. 'en 30 minutos')."
    )
    permission_level = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Que hay que recordar."},
            "due_at": {
                "type": "string",
                "description": "Fecha/hora ISO-8601 local, ej. '2026-08-20T09:00:00'.",
            },
        },
        "required": ["text", "due_at"],
    }

    def __init__(self, ctx: PluginContext):
        self._ctx = ctx

    async def run(self, text: str, due_at: str) -> ToolResult:
        try:
            datetime.fromisoformat(due_at)
        except ValueError:
            return ToolResult(success=False, content=f"Fecha invalida: '{due_at}'. Usa formato ISO-8601.")
        reminder_id = await self._ctx.memory.add_reminder(text, due_at)
        return ToolResult(
            success=True,
            content=f"Recordatorio creado para {due_at}: {text}.",
            data={"id": reminder_id},
        )


class ListRemindersTool(Tool):
    name = "list_reminders"
    description = "Lista los recordatorios pendientes."
    permission_level = PermissionLevel.READ
    parameters = {"type": "object", "properties": {}, "required": []}

    def __init__(self, ctx: PluginContext):
        self._ctx = ctx

    async def run(self) -> ToolResult:
        reminders = await self._ctx.memory.list_pending_reminders()
        if not reminders:
            return ToolResult(success=True, content="No hay recordatorios pendientes.")
        summary = "\n".join(f"- ({r['id']}) {r['due_at']}: {r['text']}" for r in reminders)
        return ToolResult(success=True, content=summary, data={"reminders": reminders})


class CancelReminderTool(Tool):
    name = "cancel_reminder"
    description = "Cancela un recordatorio pendiente por su id."
    permission_level = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {"reminder_id": {"type": "string"}},
        "required": ["reminder_id"],
    }

    def __init__(self, ctx: PluginContext):
        self._ctx = ctx

    async def run(self, reminder_id: str) -> ToolResult:
        ok = await self._ctx.memory.cancel_reminder(reminder_id)
        msg = "Recordatorio cancelado." if ok else "No se encontro ese recordatorio pendiente."
        return ToolResult(success=ok, content=msg)


class RemindersPlugin(Plugin):
    id = "reminders"
    name = "Reminders"
    version = "0.1.0"

    async def setup(self, ctx: PluginContext) -> None:
        ctx.register_tool(SetReminderTool(ctx))
        ctx.register_tool(ListRemindersTool(ctx))
        ctx.register_tool(CancelReminderTool(ctx))
        self._tz = ZoneInfo(get_settings().timezone)
        ctx.schedule_interval(lambda: self._check_due(ctx), 30.0, "reminders_plugin_check")
        log.info("Reminders plugin ready (checking every 30s)")

    async def _check_due(self, ctx: PluginContext) -> None:
        now_iso = datetime.now(self._tz).replace(tzinfo=None).isoformat(timespec="seconds")
        due = await ctx.memory.list_due_reminders(now_iso)
        for reminder in due:
            await ctx.memory.mark_reminder_fired(reminder["id"])
            await ctx.emit_event(Event(
                source="reminders", type="reminder.due",
                title="Recordatorio",
                body=reminder["text"],
                severity=0.9,
                actions=[{"id": "dismiss", "label": "Entendido"}],
                dedupe_key=f"reminder:{reminder['id']}",
            ))


PLUGIN = RemindersPlugin
