"""
EventEngine - decides what happens to an Event: ignored, stored, or pushed
to the user as a notification.

This is what keeps ALEX from being a nag. Every event gets an importance
score from a small set of rules (type weight + source severity), then:

  score <  store_threshold   -> IGNORE   (only logged)
  score >= store_threshold   -> STORE    (kept, e.g. surfaced later if asked)
  score >= notify_threshold  -> NOTIFY   (pushed via NotificationManager)

A per dedupe-key cooldown prevents the same kind of event from re-notifying
every few seconds (e.g. a system metric bouncing above/below a threshold).
"""
from __future__ import annotations

import logging
import time

from alex.core.event_bus import EventBus
from alex.events.models import Event, EventDecision
from alex.notifications.manager import NotificationManager

log = logging.getLogger(__name__)

# Base importance per event type. Unknown types default to 0.5 (mid-STORE).
# Plugins are free to raise event types not listed here.
DEFAULT_TYPE_WEIGHTS: dict[str, float] = {
    "reminder.due": 0.95,
    "calendar.upcoming": 0.85,
    "task.due_soon": 0.8,
    "system.error": 0.75,
    "system.cpu_temp_high": 0.7,
    "system.disk_high": 0.6,
    "system.service_down": 0.9,
    "system.info": 0.2,
    "plugin.info": 0.2,
}


class EventEngine:
    def __init__(
        self,
        notification_manager: NotificationManager,
        event_bus: EventBus,
        *,
        notify_threshold: float = 0.65,
        store_threshold: float = 0.3,
        cooldown_seconds: float = 1800.0,
    ):
        self._notifications = notification_manager
        self._event_bus = event_bus
        self._notify_threshold = notify_threshold
        self._store_threshold = store_threshold
        self._cooldown_seconds = cooldown_seconds
        self._last_notified_at: dict[str, float] = {}

    def _score(self, event: Event) -> float:
        base = DEFAULT_TYPE_WEIGHTS.get(event.type, 0.5)
        # Blend the type's default weight with the source's own severity hint.
        return max(0.0, min(1.0, 0.6 * base + 0.4 * event.severity))

    def _in_cooldown(self, key: str) -> bool:
        last = self._last_notified_at.get(key)
        return last is not None and (time.monotonic() - last) < self._cooldown_seconds

    async def handle(self, event: Event) -> EventDecision:
        score = self._score(event)
        key = event.dedupe_key or f"{event.source}:{event.type}"

        if score < self._store_threshold:
            decision = EventDecision.IGNORE
        elif score < self._notify_threshold:
            decision = EventDecision.STORE
        else:
            decision = EventDecision.NOTIFY if not self._in_cooldown(key) else EventDecision.STORE

        log.info(
            "Event %s/%s scored %.2f -> %s", event.source, event.type, score, decision.value
        )

        if decision == EventDecision.NOTIFY:
            self._last_notified_at[key] = time.monotonic()
            priority = _score_to_priority(score)
            await self._notifications.create(
                source=event.source,
                title=event.title,
                body=event.body,
                priority=priority,
                actions=event.actions,
            )
        elif decision == EventDecision.STORE:
            log.info("Stored (not pushed): %s - %s", event.title, event.body)

        await self._event_bus.publish("event.processed", {"event": event, "decision": decision})
        return decision


def _score_to_priority(score: float) -> int:
    """Maps a 0..1 importance score to the 0..3 notification priority scale."""
    if score >= 0.9:
        return 3  # critical
    if score >= 0.75:
        return 2  # high
    if score >= 0.5:
        return 1  # normal
    return 0  # info
