"""
Google Tasks plugin - lists/creates/completes tasks via the Google Tasks
v1 REST API directly over httpx (no Google SDK dependency).

Shares its OAuth token exchange with google_calendar_plugin.py
(alex/plugins/google_oauth.py) but uses its own client id/secret/refresh
token by default (ALEX_GOOGLE_TASKS_*) so the two integrations can be
enabled independently. If you already minted a refresh token that includes
BOTH the calendar and tasks scopes (see scripts/google_oauth_auth.py
--scopes), you can reuse the same client id/secret/refresh token for both
plugins' config values instead of authorizing twice.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from alex.config import get_settings
from alex.events.models import Event
from alex.plugins.base import Plugin, PluginContext
from alex.plugins.google_oauth import GoogleOAuthTokenSource
from alex.tools.base import PermissionLevel, Tool, ToolResult

log = logging.getLogger(__name__)

API_BASE = "https://tasks.googleapis.com/tasks/v1"


class GoogleTasksClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str, list_id: str):
        self._oauth = GoogleOAuthTokenSource(client_id, client_secret, refresh_token)
        self.list_id = list_id

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        token = await self._oauth.token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(base_url=API_BASE, headers=headers, timeout=10) as client:
            return await client.request(method, path, **kwargs)

    async def list_tasks(self, max_results: int) -> list[dict]:
        resp = await self._request("GET", f"/lists/{self.list_id}/tasks", params={
            "maxResults": max_results, "showCompleted": "false",
        })
        resp.raise_for_status()
        return resp.json().get("items", [])

    async def add_task(self, title: str, notes: str, due_date: str) -> dict:
        body: dict = {"title": title}
        if notes:
            body["notes"] = notes
        if due_date:
            # Google Tasks only honours the date portion of `due`.
            body["due"] = f"{due_date}T00:00:00.000Z"
        resp = await self._request("POST", f"/lists/{self.list_id}/tasks", json=body)
        resp.raise_for_status()
        return resp.json()

    async def complete_task(self, task_id: str) -> None:
        resp = await self._request("PATCH", f"/lists/{self.list_id}/tasks/{task_id}", json={"status": "completed"})
        resp.raise_for_status()


class TasksListTool(Tool):
    name = "tasks_list"
    description = "Lista las tareas pendientes de Google Tasks."
    permission_level = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {"max_results": {"type": "integer", "description": "Maximo de tareas (por defecto 10)."}},
        "required": [],
    }

    def __init__(self, client: GoogleTasksClient):
        self._client = client

    async def run(self, max_results: int = 10) -> ToolResult:
        tasks = await self._client.list_tasks(max_results)
        if not tasks:
            return ToolResult(success=True, content="No hay tareas pendientes.")
        summary = "\n".join(f"- ({t['id']}) {t['title']}" for t in tasks)
        return ToolResult(success=True, content=summary, data={"tasks": tasks})


class TasksAddTool(Tool):
    name = "tasks_add"
    description = "Anade una tarea nueva a Google Tasks."
    permission_level = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Titulo de la tarea."},
            "notes": {"type": "string", "description": "Notas opcionales."},
            "due_date": {"type": "string", "description": "Fecha limite, formato YYYY-MM-DD, opcional."},
        },
        "required": ["title"],
    }

    def __init__(self, client: GoogleTasksClient):
        self._client = client

    async def run(self, title: str, notes: str = "", due_date: str = "") -> ToolResult:
        task = await self._client.add_task(title, notes, due_date)
        return ToolResult(success=True, content=f"Tarea creada: {title}.", data={"id": task["id"]})


class TasksCompleteTool(Tool):
    name = "tasks_complete"
    description = "Marca una tarea de Google Tasks como completada."
    permission_level = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {"task_id": {"type": "string"}},
        "required": ["task_id"],
    }

    def __init__(self, client: GoogleTasksClient):
        self._client = client

    async def run(self, task_id: str) -> ToolResult:
        await self._client.complete_task(task_id)
        return ToolResult(success=True, content="Tarea marcada como completada.")


class GoogleTasksPlugin(Plugin):
    id = "google_tasks"
    name = "Google Tasks"
    version = "0.1.0"

    async def setup(self, ctx: PluginContext) -> None:
        settings = get_settings()
        if not all([
            settings.google_tasks_client_id,
            settings.google_tasks_client_secret,
            settings.google_tasks_refresh_token,
        ]):
            log.warning(
                "Google Tasks plugin enabled but credentials are not fully set - no tools "
                "registered. Run scripts/google_oauth_auth.py, see docs/INSTALL_RASPBERRY_PI.md."
            )
            return

        self._client = GoogleTasksClient(
            settings.google_tasks_client_id,
            settings.google_tasks_client_secret,
            settings.google_tasks_refresh_token,
            settings.google_tasks_list_id,
        )
        self._notified_task_ids: set[str] = set()

        ctx.register_tool(TasksListTool(self._client))
        ctx.register_tool(TasksAddTool(self._client))
        ctx.register_tool(TasksCompleteTool(self._client))
        ctx.schedule_interval(
            lambda: self._check(ctx), settings.google_tasks_check_interval_seconds, "google_tasks_plugin_check"
        )
        log.info("Google Tasks plugin ready (list=%s)", settings.google_tasks_list_id)

    async def _check(self, ctx: PluginContext) -> None:
        try:
            tasks = await self._client.list_tasks(50)
        except Exception:
            log.exception("Google Tasks check failed")
            return

        now = datetime.now(timezone.utc)
        for task in tasks:
            task_id = task["id"]
            due = task.get("due")
            if not due or task_id in self._notified_task_ids:
                continue
            try:
                due_at = datetime.fromisoformat(due.replace("Z", "+00:00"))
            except ValueError:
                continue
            if timedelta(0) <= due_at - now <= timedelta(hours=24):
                self._notified_task_ids.add(task_id)
                await ctx.emit_event(Event(
                    source="google_tasks", type="task.due_soon",
                    title="Tarea proxima a vencer",
                    body=task["title"],
                    severity=0.75, dedupe_key=f"google_tasks:{task_id}",
                ))


PLUGIN = GoogleTasksPlugin
