from __future__ import annotations

from datetime import datetime

import httpx
import pytest

from alex.config import Settings
from alex.plugins.installed import daily_briefing_plugin as briefing
from alex.plugins.installed.daily_briefing_plugin import (
    DailyBriefingPlugin,
    GetDailyBriefingTool,
    build_briefing_text,
    fetch_news_headlines,
    fetch_pending_tasks,
    fetch_today_events,
)

pytestmark = pytest.mark.asyncio

_RSS_SAMPLE = """<?xml version="1.0"?>
<rss><channel>
<item><title>Primera noticia</title><link>https://x/1</link></item>
<item><title>Segunda noticia</title><link>https://x/2</link></item>
<item><title>Tercera noticia</title><link>https://x/3</link></item>
</channel></rss>"""


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


async def test_fetch_news_headlines_returns_empty_without_url():
    assert await fetch_news_headlines("", 5) == []


async def test_fetch_news_headlines_parses_titles(monkeypatch):
    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, text=_RSS_SAMPLE, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    headlines = await fetch_news_headlines("https://feeds.example/rss.xml", 2)
    assert headlines == ["Primera noticia", "Segunda noticia"]


async def test_fetch_news_headlines_returns_empty_on_error(monkeypatch):
    async def fake_get(self, url, **kwargs):
        return httpx.Response(500, request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    assert await fetch_news_headlines("https://feeds.example/rss.xml", 5) == []


async def test_fetch_today_events_skips_when_not_configured():
    settings = _settings(google_calendar_client_id="", google_calendar_client_secret="", google_calendar_refresh_token="")
    assert await fetch_today_events(settings) == []


async def test_fetch_pending_tasks_skips_when_not_configured():
    settings = _settings(google_tasks_client_id="", google_tasks_client_secret="", google_tasks_refresh_token="")
    assert await fetch_pending_tasks(settings) == []


async def test_fetch_today_events_returns_summaries_when_configured(monkeypatch):
    settings = _settings(
        google_calendar_client_id="id", google_calendar_client_secret="secret", google_calendar_refresh_token="token",
    )

    async def fake_token(self):
        return "access-token"

    async def fake_get(self, url, params=None, **kwargs):
        return httpx.Response(200, json={"items": [{"summary": "Reunion"}, {"summary": "Dentista"}]}, request=httpx.Request("GET", url))

    monkeypatch.setattr("alex.plugins.installed.daily_briefing_plugin.GoogleOAuthTokenSource.token", fake_token)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    events = await fetch_today_events(settings)
    assert events == ["Reunion", "Dentista"]


async def test_fetch_today_events_returns_empty_on_error(monkeypatch):
    settings = _settings(
        google_calendar_client_id="id", google_calendar_client_secret="secret", google_calendar_refresh_token="token",
    )

    async def fake_token(self):
        raise RuntimeError("oauth failed")

    monkeypatch.setattr("alex.plugins.installed.daily_briefing_plugin.GoogleOAuthTokenSource.token", fake_token)
    assert await fetch_today_events(settings) == []


async def test_fetch_pending_tasks_returns_titles_when_configured(monkeypatch):
    settings = _settings(
        google_tasks_client_id="id", google_tasks_client_secret="secret", google_tasks_refresh_token="token",
    )

    async def fake_token(self):
        return "access-token"

    async def fake_get(self, url, params=None, **kwargs):
        return httpx.Response(200, json={"items": [{"title": "Comprar pan"}]}, request=httpx.Request("GET", url))

    monkeypatch.setattr("alex.plugins.installed.daily_briefing_plugin.GoogleOAuthTokenSource.token", fake_token)
    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)

    tasks = await fetch_pending_tasks(settings)
    assert tasks == ["Comprar pan"]


async def test_build_briefing_text_composes_all_sections(monkeypatch):
    settings = _settings(owner_name="Nicolas")

    async def fake_news(url, max_items):
        return ["Noticia A", "Noticia B"]

    async def fake_events(settings_arg):
        return ["Evento A"]

    async def fake_tasks(settings_arg):
        return ["Tarea A"]

    monkeypatch.setattr(briefing, "fetch_news_headlines", fake_news)
    monkeypatch.setattr(briefing, "fetch_today_events", fake_events)
    monkeypatch.setattr(briefing, "fetch_pending_tasks", fake_tasks)

    text = await build_briefing_text(settings)
    assert "Nicolas" in text
    assert "Evento A" in text
    assert "Tarea A" in text
    assert "Noticia A" in text and "Noticia B" in text


async def test_build_briefing_text_handles_nothing_configured(monkeypatch):
    settings = _settings()

    async def empty(*args, **kwargs):
        return []

    monkeypatch.setattr(briefing, "fetch_news_headlines", empty)
    monkeypatch.setattr(briefing, "fetch_today_events", empty)
    monkeypatch.setattr(briefing, "fetch_pending_tasks", empty)

    text = await build_briefing_text(settings)
    assert "No tienes eventos" in text
    assert "No se pudieron obtener noticias" in text


async def test_get_daily_briefing_tool_returns_built_text(monkeypatch):
    async def fake_build(settings):
        return "briefing de prueba"

    monkeypatch.setattr(briefing, "build_briefing_text", fake_build)
    result = await GetDailyBriefingTool().run()
    assert result.success is True
    assert result.content == "briefing de prueba"


class _FakeMemory:
    def __init__(self):
        self.prefs: dict[str, str] = {}

    async def get_preference(self, key: str, default: str | None = None) -> str | None:
        return self.prefs.get(key, default)

    async def set_preference(self, key: str, value: str) -> None:
        self.prefs[key] = value


class _FakeCtx:
    def __init__(self):
        self.memory = _FakeMemory()
        self.emitted: list = []
        self.plugin_config: dict = {}

    async def emit_event(self, event) -> None:
        self.emitted.append(event)

    def register_tool(self, tool) -> None:
        pass

    def schedule_interval(self, func, seconds, job_id) -> None:
        pass


async def test_check_does_not_emit_before_target_time():
    plugin = DailyBriefingPlugin()
    ctx = _FakeCtx()
    await plugin.setup(ctx)
    plugin._target_time = datetime.now(plugin._tz).time().replace(hour=23, minute=59)

    await plugin._check(ctx)
    assert ctx.emitted == []


async def test_check_emits_once_and_then_skips_same_day(monkeypatch):
    async def fake_build(settings):
        return "briefing de hoy"

    monkeypatch.setattr(briefing, "build_briefing_text", fake_build)
    plugin = DailyBriefingPlugin()
    ctx = _FakeCtx()
    await plugin.setup(ctx)
    plugin._target_time = datetime.now(plugin._tz).time().replace(hour=0, minute=0)

    await plugin._check(ctx)
    assert len(ctx.emitted) == 1
    assert ctx.emitted[0].body == "briefing de hoy"
    assert ctx.emitted[0].source == "daily_briefing"

    await plugin._check(ctx)
    assert len(ctx.emitted) == 1  # not re-sent the same day


async def test_setup_falls_back_to_default_time_on_invalid_format(monkeypatch):
    from datetime import time as dt_time

    monkeypatch.setattr(briefing, "get_settings", lambda: _settings(briefing_time="not-a-time"))
    plugin = DailyBriefingPlugin()
    ctx = _FakeCtx()
    await plugin.setup(ctx)
    assert plugin._target_time == dt_time(7, 30)
