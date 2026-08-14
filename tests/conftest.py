from __future__ import annotations

from pathlib import Path

import pytest

from alex.core.event_bus import EventBus
from alex.memory.db import Database
from alex.memory.manager import MemoryManager
from alex.notifications.manager import NotificationManager


@pytest.fixture
async def db(tmp_path: Path) -> Database:
    database = Database(tmp_path / "test_alex.db")
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def memory(db: Database) -> MemoryManager:
    return MemoryManager(db, recent_messages=20, max_facts_in_prompt=10)


@pytest.fixture
def event_bus() -> EventBus:
    return EventBus()


@pytest.fixture
async def notifications(db: Database, event_bus: EventBus) -> NotificationManager:
    return NotificationManager(db, event_bus)
