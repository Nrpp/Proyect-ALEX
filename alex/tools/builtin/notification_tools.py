from __future__ import annotations

from alex.notifications.manager import NotificationManager
from alex.tools.base import PermissionLevel, Tool, ToolResult


class SendNotificationTool(Tool):
    name = "send_notification"
    description = (
        "Crea una notificacion que se envia a todos los dispositivos conectados (consola web, "
        "apps, AlexOS si esta enlazado), ademas de tu respuesta normal en el chat. Usala cuando "
        "el usuario pida explicitamente que le avises/notifiques de algo, o para destacar algo "
        "importante fuera del hilo de la conversacion actual."
    )
    permission_level = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Titulo corto de la notificacion."},
            "body": {"type": "string", "description": "Mensaje de la notificacion."},
            "priority": {
                "type": "integer",
                "description": "0=info, 1=normal (por defecto), 2=alta, 3=critica.",
            },
        },
        "required": ["title", "body"],
    }

    def __init__(self, notifications: NotificationManager):
        self._notifications = notifications

    async def run(self, title: str, body: str, priority: int = 1) -> ToolResult:
        priority = max(0, min(int(priority), 3))
        await self._notifications.create(source="alex", title=title, body=body, priority=priority)
        return ToolResult(success=True, content=f"Notificacion enviada: {title}")
