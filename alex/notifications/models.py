from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Notification:
    id: str
    source: str
    title: str
    body: str
    priority: int = 1          # 0=info 1=normal 2=high 3=critical
    actions: list[dict] = field(default_factory=list)
    status: str = "pending"    # pending | delivered | dismissed | acted
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source": self.source,
            "title": self.title,
            "body": self.body,
            "priority": self.priority,
            "actions": self.actions,
            "status": self.status,
            "created_at": self.created_at,
        }
