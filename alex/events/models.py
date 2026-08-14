from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class EventDecision(str, Enum):
    IGNORE = "ignore"    # not useful enough to keep, only appears in debug logs
    STORE = "store"      # worth keeping a record of, but not worth interrupting the user
    NOTIFY = "notify"    # important enough to push to the user right now


@dataclass
class Event:
    """A raw occurrence raised by a plugin, the system, or a device."""

    source: str                     # e.g. "system", "reminders", "home_assistant"
    type: str                       # e.g. "system.disk_high", "reminder.due"
    title: str
    body: str
    payload: dict = field(default_factory=dict)
    severity: float = 0.5           # 0..1 hint from the source; the engine may adjust it
    actions: list[dict] = field(default_factory=list)  # e.g. [{"id": "open", "label": "Ver"}]
    dedupe_key: str | None = None   # events sharing a key are rate-limited together
