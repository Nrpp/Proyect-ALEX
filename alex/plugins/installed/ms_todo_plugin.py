"""
Microsoft To Do plugin - reads/creates/completes tasks via Microsoft Graph.

Auth uses the OAuth2 device-code flow (no client secret, no redirect URI,
nothing to run on another machine): on first run, ALEX requests a device
code from Microsoft, logs and NOTIFIES you (so it also reaches the desktop
client as a popup) with a short URL + code to enter at
https://microsoft.com/devicelogin, then polls in the background until you
approve it. The refresh token is then stored via MemoryManager preferences
(never in a file/env) and reused on restart.

Requires an Azure AD "public client" app registration (Tasks.ReadWrite
delegated permission) - see docs/INSTALL_RASPBERRY_PI.md for the exact
steps. No client secret is needed for this flow.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from alex.config import get_settings
from alex.core.errors import ToolError
from alex.events.models import Event
from alex.plugins.base import Plugin, PluginContext
from alex.tools.base import PermissionLevel, Tool, ToolResult

log = logging.getLogger(__name__)

GRAPH_BASE = "https://graph.microsoft.com/v1.0"
SCOPE = "offline_access Tasks.ReadWrite"


class MSTodoClient:
    def __init__(self, client_id: str, tenant: str, ctx: PluginContext):
        self._client_id = client_id
        self._tenant = tenant
        self._ctx = ctx
        self._access_token: str | None = None
        self._refresh_token: str | None = None
        self._expires_at: float = 0.0

    @property
    def _authority(self) -> str:
        return f"https://login.microsoftonline.com/{self._tenant}/oauth2/v2.0"

    @property
    def is_authenticated(self) -> bool:
        return self._refresh_token is not None

    async def ensure_authenticated(self) -> None:
        self._refresh_token = await self._ctx.memory.get_preference("ms_todo_refresh_token")
        if self._refresh_token:
            log.info("Microsoft To Do: usando token guardado.")
            return
        await self._device_code_flow()

    async def _device_code_flow(self) -> None:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(f"{self._authority}/devicecode", data={
                "client_id": self._client_id, "scope": SCOPE,
            })
        if resp.status_code != 200:
            log.error("Microsoft To Do: fallo al solicitar el codigo de dispositivo: %s", resp.text)
            return
        data = resp.json()

        log.warning(
            "MICROSOFT TO DO SIN AUTORIZAR: ve a %s e introduce el codigo %s (expira en %d min).",
            data["verification_uri"], data["user_code"], data.get("expires_in", 900) // 60,
        )
        await self._ctx.emit_event(Event(
            source="ms_todo", type="integration.auth_required",
            title="Autorizacion necesaria: Microsoft To Do",
            body=f"Ve a {data['verification_uri']} e introduce el codigo {data['user_code']}.",
            severity=1.0,
        ))

        interval = data.get("interval", 5)
        device_code = data["device_code"]
        deadline = time.monotonic() + data.get("expires_in", 900)

        async with httpx.AsyncClient(timeout=15) as client:
            while time.monotonic() < deadline:
                await asyncio.sleep(interval)
                resp = await client.post(f"{self._authority}/token", data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": self._client_id,
                    "device_code": device_code,
                })
                payload = resp.json()
                if resp.status_code == 200:
                    self._access_token = payload["access_token"]
                    self._expires_at = time.monotonic() + payload.get("expires_in", 3600)
                    self._refresh_token = payload["refresh_token"]
                    await self._ctx.memory.set_preference("ms_todo_refresh_token", self._refresh_token)
                    log.info("Microsoft To Do autorizado correctamente.")
                    await self._ctx.emit_event(Event(
                        source="ms_todo", type="integration.auth_required",
                        title="Microsoft To Do conectado",
                        body="Autorizacion completada, ya puedo consultar tus tareas.",
                        severity=0.6,
                    ))
                    return
                error = payload.get("error")
                if error == "authorization_pending":
                    continue
                if error == "slow_down":
                    interval += 5
                    continue
                log.error("Microsoft To Do: fallo la autorizacion (%s).", error)
                return
        log.error("Microsoft To Do: tiempo de espera agotado para autorizar.")

    async def _token(self) -> str:
        if self._access_token and time.monotonic() < self._expires_at - 60:
            return self._access_token
        if not self._refresh_token:
            raise ToolError(
                "Microsoft To Do todavia no esta autorizado - revisa los logs "
                "(journalctl -u alex) para el codigo de autorizacion."
            )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(f"{self._authority}/token", data={
                "grant_type": "refresh_token",
                "client_id": self._client_id,
                "refresh_token": self._refresh_token,
                "scope": SCOPE,
            })
        if resp.status_code != 200:
            raise ToolError(f"No se pudo renovar el token de Microsoft To Do: {resp.text}")
        data = resp.json()
        self._access_token = data["access_token"]
        self._expires_at = time.monotonic() + data.get("expires_in", 3600)
        if "refresh_token" in data:
            self._refresh_token = data["refresh_token"]
            await self._ctx.memory.set_preference("ms_todo_refresh_token", self._refresh_token)
        return self._access_token

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        token = await self._token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(base_url=GRAPH_BASE, headers=headers, timeout=10) as client:
            return await client.request(method, path, **kwargs)

    async def _resolve_list_id(self, list_name: str) -> str:
        resp = await self._request("GET", "/me/todo/lists")
        resp.raise_for_status()
        lists = resp.json().get("value", [])
        for lst in lists:
            if lst["displayName"].lower() == list_name.lower():
                return lst["id"]
        if not lists:
            raise ToolError("No se encontraron listas de tareas en Microsoft To Do.")
        return lists[0]["id"]

    async def list_tasks(self, list_name: str, limit: int) -> list[dict]:
        list_id = await self._resolve_list_id(list_name)
        resp = await self._request("GET", f"/me/todo/lists/{list_id}/tasks", params={"$top": limit})
        resp.raise_for_status()
        return [t for t in resp.json().get("value", []) if t.get("status") != "completed"]

    async def add_task(self, title: str, list_name: str, due_date: str | None) -> dict:
        list_id = await self._resolve_list_id(list_name)
        body: dict = {"title": title}
        if due_date:
            body["dueDateTime"] = {"dateTime": due_date, "timeZone": "UTC"}
        resp = await self._request("POST", f"/me/todo/lists/{list_id}/tasks", json=body)
        resp.raise_for_status()
        return resp.json()

    async def complete_task(self, task_id: str, list_name: str) -> None:
        list_id = await self._resolve_list_id(list_name)
        resp = await self._request("PATCH", f"/me/todo/lists/{list_id}/tasks/{task_id}", json={"status": "completed"})
        resp.raise_for_status()


class TodoListTasksTool(Tool):
    name = "todo_list_tasks"
    description = "Lista las tareas pendientes de Microsoft To Do."
    permission_level = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {
            "list_name": {"type": "string", "description": "Nombre de la lista (por defecto 'Tasks')."},
            "limit": {"type": "integer", "description": "Maximo de tareas (por defecto 10)."},
        },
        "required": [],
    }

    def __init__(self, client: MSTodoClient):
        self._client = client

    async def run(self, list_name: str = "Tasks", limit: int = 10) -> ToolResult:
        tasks = await self._client.list_tasks(list_name, limit)
        if not tasks:
            return ToolResult(success=True, content="No hay tareas pendientes.")
        summary = "\n".join(f"- ({t['id']}) {t['title']}" for t in tasks)
        return ToolResult(success=True, content=summary, data={"tasks": tasks})


class TodoAddTaskTool(Tool):
    name = "todo_add_task"
    description = "Anade una tarea nueva a Microsoft To Do."
    permission_level = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Titulo de la tarea."},
            "list_name": {"type": "string", "description": "Lista destino (por defecto 'Tasks')."},
            "due_date": {"type": "string", "description": "Fecha limite ISO-8601 UTC, opcional."},
        },
        "required": ["title"],
    }

    def __init__(self, client: MSTodoClient):
        self._client = client

    async def run(self, title: str, list_name: str = "Tasks", due_date: str | None = None) -> ToolResult:
        task = await self._client.add_task(title, list_name, due_date)
        return ToolResult(success=True, content=f"Tarea creada: {title}.", data={"id": task["id"]})


class TodoCompleteTaskTool(Tool):
    name = "todo_complete_task"
    description = "Marca una tarea de Microsoft To Do como completada."
    permission_level = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "task_id": {"type": "string"},
            "list_name": {"type": "string", "description": "Lista de la tarea (por defecto 'Tasks')."},
        },
        "required": ["task_id"],
    }

    def __init__(self, client: MSTodoClient):
        self._client = client

    async def run(self, task_id: str, list_name: str = "Tasks") -> ToolResult:
        await self._client.complete_task(task_id, list_name)
        return ToolResult(success=True, content="Tarea marcada como completada.")


class MSTodoPlugin(Plugin):
    id = "ms_todo"
    name = "Microsoft To Do"
    version = "0.1.0"

    async def setup(self, ctx: PluginContext) -> None:
        settings = get_settings()
        if not settings.ms_client_id:
            log.warning(
                "Microsoft To Do plugin enabled but ALEX_MS_CLIENT_ID is not set - no tools "
                "registered. See docs/INSTALL_RASPBERRY_PI.md."
            )
            return

        self._client = MSTodoClient(settings.ms_client_id, settings.ms_tenant, ctx)
        self._notified_task_ids: set[str] = set()

        ctx.register_tool(TodoListTasksTool(self._client))
        ctx.register_tool(TodoAddTaskTool(self._client))
        ctx.register_tool(TodoCompleteTaskTool(self._client))
        ctx.schedule_interval(
            lambda: self._check(ctx), settings.ms_todo_check_interval_seconds, "ms_todo_plugin_check"
        )

        # Non-blocking: device-code auth (if needed) polls in the background
        # without delaying the rest of ALEX's startup.
        asyncio.create_task(self._client.ensure_authenticated())
        log.info("Microsoft To Do plugin ready (tenant=%s)", settings.ms_tenant)

    async def _check(self, ctx: PluginContext) -> None:
        if not self._client.is_authenticated:
            return  # not authenticated yet
        try:
            tasks = await self._client.list_tasks("Tasks", 20)
        except Exception:
            log.exception("Microsoft To Do check failed")
            return

        now = datetime.now(timezone.utc)
        for task in tasks:
            task_id = task["id"]
            due = task.get("dueDateTime")
            if not due or task_id in self._notified_task_ids:
                continue
            try:
                due_at = datetime.fromisoformat(due["dateTime"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if timedelta(0) <= due_at - now <= timedelta(hours=24):
                self._notified_task_ids.add(task_id)
                await ctx.emit_event(Event(
                    source="ms_todo", type="task.due_soon",
                    title="Tarea proxima a vencer",
                    body=task["title"],
                    severity=0.75, dedupe_key=f"ms_todo:{task_id}",
                ))


PLUGIN = MSTodoPlugin
