from __future__ import annotations

import pytest

from alex.events.engine import EventEngine
from alex.events.models import Event, EventDecision

pytestmark = pytest.mark.asyncio


async def test_low_importance_event_is_ignored(notifications, event_bus):
    engine = EventEngine(notifications, event_bus, notify_threshold=0.65, store_threshold=0.3)
    decision = await engine.handle(Event(source="test", type="system.info", title="t", body="b", severity=0.1))
    assert decision == EventDecision.IGNORE
    assert await notifications.list_recent() == []


async def test_important_event_notifies(notifications, event_bus):
    engine = EventEngine(notifications, event_bus, notify_threshold=0.65, store_threshold=0.3)
    decision = await engine.handle(
        Event(source="reminders", type="reminder.due", title="Recordatorio", body="Examen", severity=0.9)
    )
    assert decision == EventDecision.NOTIFY
    recent = await notifications.list_recent()
    assert len(recent) == 1
    assert recent[0].title == "Recordatorio"


async def test_cooldown_suppresses_repeat_notifications(notifications, event_bus):
    engine = EventEngine(notifications, event_bus, notify_threshold=0.65, store_threshold=0.3, cooldown_seconds=9999)
    event = Event(source="system", type="system.disk_high", title="Disco", body="90%", severity=0.9,
                   dedupe_key="system:disk")

    first = await engine.handle(event)
    second = await engine.handle(event)

    assert first == EventDecision.NOTIFY
    assert second == EventDecision.STORE  # same dedupe key, still in cooldown
    assert len(await notifications.list_recent()) == 1
