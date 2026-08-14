"""Plain data types returned by the MemoryManager (no ORM, kept simple on purpose)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Message:
    role: str
    content: str
    created_at: str = ""


@dataclass
class MemoryItem:
    id: int
    kind: str
    content: str
    tags: list[str] = field(default_factory=list)
    project: str | None = None
    importance: float = 0.5
    created_at: str = ""


@dataclass
class Fact:
    key: str
    value: str
    category: str = "general"
    confidence: float = 1.0
    source: str = "user"
