"""
NotificationManager - creates, persists and hands off notifications.

It never talks WebSocket directly: it publishes "notification.created" on
the EventBus and the server's WS layer (alex/server/ws.py) is the one
subscriber that actually pushes bytes to connected clients. This means
NotificationManager works the same whether zero or ten clients are
connected, and new delivery channels (e.g. push notifications to a phone
later) just add another subscriber.
"""
from __future__ import annotations

import json
import logging
import uuid

from alex.core.event_bus import EventBus
from alex.memory.db import Database
from alex.notifications.models import Notification

log = logging.getLogger(__name__)


class NotificationManager:
    def __init__(self, db: Database, event_bus: EventBus):
        self._db = db
        self._event_bus = event_bus

    async def create(
        self,
        *,
        source: str,
        title: str,
        body: str,
        priority: int = 1,
        actions: list[dict] | None = None,
    ) -> Notification:
        notif_id = str(uuid.uuid4())
        actions = actions or []
        await self._db.conn.execute(
            """INSERT INTO notifications (id, source, title, body, priority, actions, status)
               VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
            (notif_id, source, title, body, priority, json.dumps(actions)),
        )
        await self._db.conn.commit()
        cursor = await self._db.conn.execute(
            "SELECT created_at FROM notifications WHERE id = ?", (notif_id,)
        )
        row = await cursor.fetchone()

        notification = Notification(
            id=notif_id, source=source, title=title, body=body,
            priority=priority, actions=actions, status="pending",
            created_at=row["created_at"] if row else "",
        )
        log.info("Notification created: [%s] %s - %s", source, title, body)
        await self._event_bus.publish("notification.created", notification)
        return notification

    async def mark_status(self, notification_id: str, status: str) -> bool:
        cursor = await self._db.conn.execute(
            "UPDATE notifications SET status = ?, updated_at = datetime('now') WHERE id = ?",
            (status, notification_id),
        )
        await self._db.conn.commit()
        return cursor.rowcount > 0

    async def get(self, notification_id: str) -> Notification | None:
        cursor = await self._db.conn.execute(
            "SELECT * FROM notifications WHERE id = ?", (notification_id,)
        )
        row = await cursor.fetchone()
        return _row_to_notification(row) if row else None

    async def list_recent(self, limit: int = 20, status: str | None = None) -> list[Notification]:
        sql = "SELECT * FROM notifications"
        params: list = []
        if status:
            sql += " WHERE status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        cursor = await self._db.conn.execute(sql, params)
        rows = await cursor.fetchall()
        return [_row_to_notification(r) for r in rows]


def _row_to_notification(row) -> Notification:
    return Notification(
        id=row["id"], source=row["source"], title=row["title"], body=row["body"],
        priority=row["priority"], actions=json.loads(row["actions"]), status=row["status"],
        created_at=row["created_at"],
    )
