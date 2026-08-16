from __future__ import annotations

import pytest

from alex.ai.base import AIProvider, AIResponse
from alex.config import Settings
from alex.core.core import ALEXCore
from alex.tools.base import PermissionLevel

pytestmark = pytest.mark.asyncio


class SilentProvider(AIProvider):
    name = "silent"

    async def complete(self, messages, *, system, tools=None, max_tokens=1024, temperature=0.4):
        return AIResponse(content="ok")

    async def health_check(self) -> bool:
        return True


async def _make_core(tmp_path) -> ALEXCore:
    settings = Settings(
        db_path=tmp_path / "test_alex.db",
        log_dir=tmp_path / "logs",
        data_dir=tmp_path,
        enabled_plugins=[],
    )
    core = ALEXCore(settings)
    core.ai = SilentProvider()
    await core.start()
    return core


async def test_send_notification_is_registered_and_write_level(tmp_path):
    core = await _make_core(tmp_path)
    try:
        tool = core.tools.get("send_notification")
        assert tool is not None
        assert tool.permission_level == PermissionLevel.WRITE
    finally:
        await core.shutdown()


async def test_send_notification_creates_a_real_notification(tmp_path):
    core = await _make_core(tmp_path)
    try:
        result = await core.tools.execute(
            "send_notification", {"title": "Riego terminado", "body": "El jardin ya esta regado.", "priority": 2}
        )
        assert result.success is True

        recent = await core.notifications.list_recent(limit=5)
        assert len(recent) == 1
        assert recent[0].title == "Riego terminado"
        assert recent[0].body == "El jardin ya esta regado."
        assert recent[0].priority == 2
        assert recent[0].source == "alex"
    finally:
        await core.shutdown()


async def test_send_notification_defaults_priority_to_normal(tmp_path):
    core = await _make_core(tmp_path)
    try:
        await core.tools.execute("send_notification", {"title": "Hola", "body": "Solo un aviso."})
        recent = await core.notifications.list_recent(limit=5)
        assert recent[0].priority == 1
    finally:
        await core.shutdown()


async def test_send_notification_clamps_out_of_range_priority(tmp_path):
    core = await _make_core(tmp_path)
    try:
        await core.tools.execute("send_notification", {"title": "Hola", "body": "Aviso.", "priority": 99})
        recent = await core.notifications.list_recent(limit=5)
        assert recent[0].priority == 3
    finally:
        await core.shutdown()
