"""
Web Push delivery - reaches an installed PWA (the web console added to a
phone's home screen; iOS 16.4+ supports this) even while it isn't open,
by pushing through the browser's push service rather than over ALEX's own
WebSocket (which only works while a client is actively connected).

Requires ALEX_VAPID_PUBLIC_KEY / ALEX_VAPID_PRIVATE_KEY (generate with
`python3 scripts/gen_vapid_keys.py`) and ALEX_VAPID_CONTACT_EMAIL. Without
them, WebPushSender.send_to_all() is a silent no-op - Web Push is opt-in,
not required for ALEX to run.
"""
from __future__ import annotations

import json
import logging
import uuid

from pywebpush import WebPushException, webpush_async

from alex.memory.db import Database
from alex.notifications.models import Notification

log = logging.getLogger(__name__)


class PushSubscriptionStore:
    """CRUD for browser push subscriptions. Talks to Database directly,
    same style as NotificationManager - this isn't conversational memory,
    it's delivery-channel bookkeeping."""

    def __init__(self, db: Database):
        self._db = db

    async def add(self, endpoint: str, p256dh: str, auth: str) -> None:
        await self._db.conn.execute(
            """INSERT INTO push_subscriptions (id, endpoint, p256dh, auth) VALUES (?, ?, ?, ?)
               ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth""",
            (str(uuid.uuid4()), endpoint, p256dh, auth),
        )
        await self._db.conn.commit()

    async def remove(self, endpoint: str) -> None:
        await self._db.conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        await self._db.conn.commit()

    async def list_all(self) -> list[dict]:
        cursor = await self._db.conn.execute("SELECT endpoint, p256dh, auth FROM push_subscriptions")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]


class WebPushSender:
    def __init__(
        self,
        store: PushSubscriptionStore,
        vapid_private_key: str,
        vapid_contact_email: str,
    ):
        self._store = store
        self._private_key = vapid_private_key
        self._claims_sub = f"mailto:{vapid_contact_email}" if vapid_contact_email else ""

    @property
    def is_configured(self) -> bool:
        return bool(self._private_key and self._claims_sub)

    async def send_to_all(self, notification: Notification) -> None:
        if not self.is_configured:
            return
        subscriptions = await self._store.list_all()
        if not subscriptions:
            return
        payload = json.dumps(
            {
                "id": notification.id,
                "title": notification.title,
                "body": notification.body,
                "priority": notification.priority,
            }
        )
        for subscription in subscriptions:
            await self._send_one(subscription, payload)

    async def _send_one(self, subscription: dict, payload: str) -> None:
        subscription_info = {
            "endpoint": subscription["endpoint"],
            "keys": {"p256dh": subscription["p256dh"], "auth": subscription["auth"]},
        }
        try:
            await webpush_async(
                subscription_info=subscription_info,
                data=payload,
                vapid_private_key=self._private_key,
                vapid_claims={"sub": self._claims_sub},
                timeout=10,
            )
        except WebPushException as e:
            status = getattr(e.response, "status", None)
            if status in (404, 410):
                # The push service itself is telling us this subscription
                # will never work again (browser data cleared, PWA
                # uninstalled, ...) - not a transient failure, so there's
                # no point keeping it around to fail every future push too.
                log.info("Push subscription gone (status=%s), removing it", status)
                await self._store.remove(subscription["endpoint"])
            else:
                log.warning("Web push failed (status=%s): %s", status, e)
        except Exception:
            log.exception("Unexpected error sending a web push notification")
