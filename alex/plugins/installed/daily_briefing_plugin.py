"""
Daily briefing plugin - "decirme las noticias de la manana": once a day, at
ALEX_BRIEFING_TIME (local time), ALEX composes a short briefing (news +,
if configured, today's calendar events, pending tasks and unread emails)
and pushes it as
a normal notification - which also gets spoken aloud if voice_enabled (see
alex/voice/pipeline.py's announce filter). The same content is available
on demand any time via the get_daily_briefing tool, no need to wait for
the scheduled time.

News uses the same feed + RSS parsing approach as AlexOS's modules/news
(xml.etree, standard library, no feedparser dependency) - duplicated
rather than imported, ALEX and AlexOS are separate deployable projects.

Calendar/tasks/email reuse the SAME credentials as google_calendar_plugin.py
/ google_tasks_plugin.py / email_plugin.py (ALEX_GOOGLE_CALENDAR_*,
ALEX_GOOGLE_TASKS_*, ALEX_GOOGLE_GMAIL_*) via the shared
alex.plugins.google_oauth token exchange, but built as their own minimal
client here rather than importing those plugin modules - plugins don't
depend on each other, only on shared library code. Missing credentials
just mean that section is silently skipped, not an error - news alone is
enough to satisfy "tell me the morning news" out of the box.
"""
from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ElementTree
from datetime import datetime, time as dt_time, timezone
from zoneinfo import ZoneInfo

import httpx

from alex.config import get_settings
from alex.events.models import Event
from alex.plugins.base import Plugin, PluginContext
from alex.plugins.google_oauth import GoogleOAuthTokenSource
from alex.tools.base import PermissionLevel, Tool, ToolResult

log = logging.getLogger(__name__)

CALENDAR_API_BASE = "https://www.googleapis.com/calendar/v3"
TASKS_API_BASE = "https://tasks.googleapis.com/tasks/v1"
GMAIL_API_BASE = "https://gmail.googleapis.com/gmail/v1"
_LAST_SENT_PREFERENCE_KEY = "daily_briefing_last_sent_date"


async def fetch_news_headlines(rss_url: str, max_items: int) -> list[str]:
    if not rss_url:
        return []
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(rss_url)
        resp.raise_for_status()
        root = ElementTree.fromstring(resp.text)
    except Exception:
        log.exception("Daily briefing: news fetch failed")
        return []
    return [
        title for item in root.findall("./channel/item")[:max_items]
        if (title := item.findtext("title", default="").strip())
    ]


async def fetch_today_events(settings) -> list[str]:
    if not all([settings.google_calendar_client_id, settings.google_calendar_client_secret, settings.google_calendar_refresh_token]):
        return []
    oauth = GoogleOAuthTokenSource(
        settings.google_calendar_client_id, settings.google_calendar_client_secret, settings.google_calendar_refresh_token
    )
    now = datetime.now(timezone.utc)
    end_of_day_local = datetime.now(ZoneInfo(settings.timezone)).replace(hour=23, minute=59, second=59)
    try:
        token = await oauth.token()
        async with httpx.AsyncClient(base_url=CALENDAR_API_BASE, headers={"Authorization": f"Bearer {token}"}, timeout=10) as client:
            resp = await client.get(f"/calendars/{settings.google_calendar_id}/events", params={
                "timeMin": now.isoformat(),
                "timeMax": end_of_day_local.astimezone(timezone.utc).isoformat(),
                "maxResults": 10,
                "singleEvents": "true",
                "orderBy": "startTime",
            })
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except Exception:
        log.exception("Daily briefing: calendar fetch failed")
        return []
    return [item.get("summary", "(sin titulo)") for item in items]


async def fetch_pending_tasks(settings) -> list[str]:
    if not all([settings.google_tasks_client_id, settings.google_tasks_client_secret, settings.google_tasks_refresh_token]):
        return []
    oauth = GoogleOAuthTokenSource(
        settings.google_tasks_client_id, settings.google_tasks_client_secret, settings.google_tasks_refresh_token
    )
    try:
        token = await oauth.token()
        async with httpx.AsyncClient(base_url=TASKS_API_BASE, headers={"Authorization": f"Bearer {token}"}, timeout=10) as client:
            resp = await client.get(f"/lists/{settings.google_tasks_list_id}/tasks", params={"maxResults": 10, "showCompleted": "false"})
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except Exception:
        log.exception("Daily briefing: tasks fetch failed")
        return []
    return [item["title"] for item in items]


async def fetch_unread_emails(settings) -> list[str]:
    if not all([settings.google_gmail_client_id, settings.google_gmail_client_secret, settings.google_gmail_refresh_token]):
        return []
    oauth = GoogleOAuthTokenSource(
        settings.google_gmail_client_id, settings.google_gmail_client_secret, settings.google_gmail_refresh_token
    )
    try:
        token = await oauth.token()
        headers = {"Authorization": f"Bearer {token}"}
        async with httpx.AsyncClient(base_url=GMAIL_API_BASE, headers=headers, timeout=10) as client:
            resp = await client.get("/users/me/messages", params={
                "q": "is:unread", "maxResults": settings.briefing_email_max_items,
            })
            resp.raise_for_status()
            refs = resp.json().get("messages", [])
            headlines = []
            for ref in refs:
                detail = await client.get(f"/users/me/messages/{ref['id']}", params={
                    "format": "metadata", "metadataHeaders": ["Subject", "From"],
                })
                detail.raise_for_status()
                msg_headers = {h["name"]: h["value"] for h in detail.json().get("payload", {}).get("headers", [])}
                sender = msg_headers.get("From", "").split("<")[0].strip()
                headlines.append(f"{sender}: {msg_headers.get('Subject', '(sin asunto)')}")
    except Exception:
        log.exception("Daily briefing: email fetch failed")
        return []
    return headlines


async def build_briefing_text(settings) -> str:
    news, events, tasks, emails = await asyncio.gather(
        fetch_news_headlines(settings.briefing_news_rss_url, settings.briefing_news_max_items),
        fetch_today_events(settings),
        fetch_pending_tasks(settings),
        fetch_unread_emails(settings),
    )

    sections = [f"Buenos dias, {settings.owner_name}."]

    if events:
        sections.append("Hoy en tu agenda: " + "; ".join(events) + ".")
    else:
        sections.append("No tienes eventos en el calendario para hoy.")

    if tasks:
        sections.append("Tareas pendientes: " + "; ".join(tasks) + ".")

    if emails:
        sections.append("Correos sin leer: " + "; ".join(emails) + ".")

    if news:
        sections.append("Noticias: " + " | ".join(news) + ".")
    else:
        sections.append("No se pudieron obtener noticias en este momento.")

    return " ".join(sections)


class GetDailyBriefingTool(Tool):
    name = "get_daily_briefing"
    description = (
        "Genera el briefing del dia (noticias + agenda de hoy + tareas pendientes + correos sin "
        "leer, segun este configurado) al momento, sin esperar a la hora programada. Usa esto "
        "cuando el usuario pida las noticias, un resumen del dia, o similar."
    )
    permission_level = PermissionLevel.READ
    parameters = {"type": "object", "properties": {}, "required": []}

    async def run(self) -> ToolResult:
        text = await build_briefing_text(get_settings())
        return ToolResult(success=True, content=text)


class DailyBriefingPlugin(Plugin):
    id = "daily_briefing"
    name = "Daily Briefing"
    version = "0.1.0"

    async def setup(self, ctx: PluginContext) -> None:
        settings = get_settings()
        self._tz = ZoneInfo(settings.timezone)
        try:
            hour_str, minute_str = settings.briefing_time.split(":")
            self._target_time = dt_time(int(hour_str), int(minute_str))
        except ValueError:
            log.error("ALEX_BRIEFING_TIME='%s' invalido (esperado 'HH:MM'), usando 07:30", settings.briefing_time)
            self._target_time = dt_time(7, 30)

        ctx.register_tool(GetDailyBriefingTool())
        ctx.schedule_interval(lambda: self._check(ctx), 60.0, "daily_briefing_plugin_check")
        log.info("Daily briefing plugin ready (hora=%s)", self._target_time.strftime("%H:%M"))

    async def _check(self, ctx: PluginContext) -> None:
        now = datetime.now(self._tz)
        if now.time() < self._target_time:
            return
        today_str = now.date().isoformat()
        if await ctx.memory.get_preference(_LAST_SENT_PREFERENCE_KEY) == today_str:
            return

        text = await build_briefing_text(get_settings())
        await ctx.memory.set_preference(_LAST_SENT_PREFERENCE_KEY, today_str)
        await ctx.emit_event(Event(
            source="daily_briefing", type="daily.briefing",
            title="Briefing de hoy", body=text,
            severity=0.95, dedupe_key=f"daily_briefing:{today_str}",
        ))


PLUGIN = DailyBriefingPlugin
