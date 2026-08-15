"""
Google Calendar plugin - reads/creates/deletes events via the Calendar v3
REST API directly over httpx (no Google SDK dependency, consistent with the
rest of ALEX's integrations).

One-time setup required outside ALEX: create an OAuth2 "Desktop app" client
in Google Cloud Console, then run `scripts/google_calendar_auth.py` on a
machine with a browser (NOT the Pi) to mint a refresh token - see
docs/INSTALL_RASPBERRY_PI.md. ALEX only ever holds the long-lived refresh
token + client id/secret; access tokens are minted on demand and cached in
memory for their lifetime (~1h).
"""
from __future__ import annotations

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

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_BASE = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarClient:
    def __init__(self, client_id: str, client_secret: str, refresh_token: str, calendar_id: str):
        self._client_id = client_id
        self._client_secret = client_secret
        self._refresh_token = refresh_token
        self.calendar_id = calendar_id
        self._access_token: str | None = None
        self._expires_at: float = 0.0

    async def _token(self) -> str:
        if self._access_token and time.monotonic() < self._expires_at - 60:
            return self._access_token
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(TOKEN_URL, data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            })
        if resp.status_code != 200:
            raise ToolError(f"No se pudo renovar el token de Google Calendar: {resp.text}")
        data = resp.json()
        self._access_token = data["access_token"]
        self._expires_at = time.monotonic() + data.get("expires_in", 3600)
        return self._access_token

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        token = await self._token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(base_url=API_BASE, headers=headers, timeout=10) as client:
            return await client.request(method, path, **kwargs)

    async def list_upcoming(self, max_results: int, days_ahead: int) -> list[dict]:
        now = datetime.now(timezone.utc)
        params = {
            "timeMin": now.isoformat(),
            "timeMax": (now + timedelta(days=days_ahead)).isoformat(),
            "maxResults": max_results,
            "singleEvents": "true",
            "orderBy": "startTime",
        }
        resp = await self._request("GET", f"/calendars/{self.calendar_id}/events", params=params)
        resp.raise_for_status()
        return resp.json().get("items", [])

    async def create_event(self, summary: str, start_iso: str, end_iso: str, description: str) -> dict:
        body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_iso},
            "end": {"dateTime": end_iso},
        }
        resp = await self._request("POST", f"/calendars/{self.calendar_id}/events", json=body)
        resp.raise_for_status()
        return resp.json()

    async def delete_event(self, event_id: str) -> None:
        resp = await self._request("DELETE", f"/calendars/{self.calendar_id}/events/{event_id}")
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()


class CalendarListUpcomingTool(Tool):
    name = "calendar_list_upcoming"
    description = "Lista los proximos eventos del calendario de Google."
    permission_level = PermissionLevel.READ
    parameters = {
        "type": "object",
        "properties": {
            "max_results": {"type": "integer", "description": "Maximo de eventos (por defecto 5)."},
            "days_ahead": {"type": "integer", "description": "Dias hacia adelante a mirar (por defecto 7)."},
        },
        "required": [],
    }

    def __init__(self, client: GoogleCalendarClient):
        self._client = client

    async def run(self, max_results: int = 5, days_ahead: int = 7) -> ToolResult:
        events = await self._client.list_upcoming(max_results, days_ahead)
        if not events:
            return ToolResult(success=True, content="No hay eventos proximos.")
        summary = "\n".join(
            f"- ({e['id']}) {e.get('summary', '(sin titulo)')}: {_event_time(e)}" for e in events
        )
        return ToolResult(success=True, content=summary, data={"events": events})


class CalendarCreateEventTool(Tool):
    name = "calendar_create_event"
    description = "Crea un evento nuevo en el calendario de Google."
    permission_level = PermissionLevel.WRITE
    parameters = {
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "Titulo del evento."},
            "start_iso": {"type": "string", "description": "Inicio, ISO-8601 con zona horaria."},
            "end_iso": {"type": "string", "description": "Fin, ISO-8601 con zona horaria."},
            "description": {"type": "string", "description": "Descripcion opcional."},
        },
        "required": ["summary", "start_iso", "end_iso"],
    }

    def __init__(self, client: GoogleCalendarClient):
        self._client = client

    async def run(self, summary: str, start_iso: str, end_iso: str, description: str = "") -> ToolResult:
        event = await self._client.create_event(summary, start_iso, end_iso, description)
        return ToolResult(success=True, content=f"Evento creado: {summary} ({start_iso}).", data={"id": event["id"]})


class CalendarDeleteEventTool(Tool):
    name = "calendar_delete_event"
    description = "Elimina un evento del calendario de Google por su id. Accion destructiva."
    permission_level = PermissionLevel.CONFIRM
    parameters = {
        "type": "object",
        "properties": {"event_id": {"type": "string"}},
        "required": ["event_id"],
    }

    def __init__(self, client: GoogleCalendarClient):
        self._client = client

    async def run(self, event_id: str) -> ToolResult:
        await self._client.delete_event(event_id)
        return ToolResult(success=True, content=f"Evento {event_id} eliminado.")


def _event_time(event: dict) -> str:
    start = event.get("start", {})
    return start.get("dateTime") or start.get("date") or "?"


class GoogleCalendarPlugin(Plugin):
    id = "google_calendar"
    name = "Google Calendar"
    version = "0.1.0"

    async def setup(self, ctx: PluginContext) -> None:
        settings = get_settings()
        if not all([
            settings.google_calendar_client_id,
            settings.google_calendar_client_secret,
            settings.google_calendar_refresh_token,
        ]):
            log.warning(
                "Google Calendar plugin enabled but credentials are not fully set - no tools "
                "registered. Run scripts/google_calendar_auth.py, see docs/INSTALL_RASPBERRY_PI.md."
            )
            return

        self._client = GoogleCalendarClient(
            settings.google_calendar_client_id,
            settings.google_calendar_client_secret,
            settings.google_calendar_refresh_token,
            settings.google_calendar_id,
        )
        self._notified_event_ids: set[str] = set()

        ctx.register_tool(CalendarListUpcomingTool(self._client))
        ctx.register_tool(CalendarCreateEventTool(self._client))
        ctx.register_tool(CalendarDeleteEventTool(self._client))
        ctx.schedule_interval(
            lambda: self._check(ctx), settings.google_calendar_check_interval_seconds, "google_calendar_plugin_check"
        )
        log.info("Google Calendar plugin ready (calendar=%s)", settings.google_calendar_id)

    async def _check(self, ctx: PluginContext) -> None:
        try:
            events = await self._client.list_upcoming(max_results=10, days_ahead=1)
        except Exception:
            log.exception("Google Calendar check failed")
            return

        now = datetime.now(timezone.utc)
        for event in events:
            event_id = event["id"]
            if event_id in self._notified_event_ids:
                continue
            start_str = _event_time(event)
            try:
                start = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            minutes_until = (start - now).total_seconds() / 60
            if 0 <= minutes_until <= 60:
                self._notified_event_ids.add(event_id)
                await ctx.emit_event(Event(
                    source="google_calendar", type="calendar.upcoming",
                    title="Evento proximo",
                    body=f"{event.get('summary', '(sin titulo)')} en {int(minutes_until)} min.",
                    severity=0.8, dedupe_key=f"calendar:{event_id}",
                ))


PLUGIN = GoogleCalendarPlugin
