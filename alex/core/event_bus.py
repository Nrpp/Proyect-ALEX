"""
Internal async pub/sub bus.

This is the decoupling backbone of ALEX: the voice pipeline, plugins, the
event engine, the scheduler and the API layer never call each other
directly - they publish and subscribe to named topics here. This keeps the
Core swappable and testable, and means adding a plugin never requires
touching unrelated modules.

Topics used across the codebase (informal convention, not enforced):
  "message.incoming"      - a user utterance/text arrived, needs a reply
  "message.outgoing"      - ALEX produced a reply
  "event.raised"          - a plugin/system raised a raw Event for evaluation
  "notification.created"  - the NotificationManager created a notification to push
  "tool.confirmation_needed" - a CONFIRM-level tool call is waiting on the user
  "system.shutdown"       - graceful shutdown requested
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

log = logging.getLogger(__name__)

Handler = Callable[[Any], Awaitable[None]] | Callable[[Any], None]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[Handler]] = defaultdict(list)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subscribers[topic].append(handler)
        log.debug("Subscribed %s to topic '%s'", getattr(handler, "__qualname__", handler), topic)

    def unsubscribe(self, topic: str, handler: Handler) -> None:
        if handler in self._subscribers.get(topic, []):
            self._subscribers[topic].remove(handler)

    async def publish(self, topic: str, payload: Any = None) -> None:
        handlers = list(self._subscribers.get(topic, []))
        if not handlers:
            log.debug("Published '%s' with no subscribers", topic)
            return
        for handler in handlers:
            try:
                result = handler(payload)
                if asyncio.iscoroutine(result):
                    await result
            except Exception:
                log.exception("Handler for topic '%s' raised an exception", topic)

    def publish_soon(self, topic: str, payload: Any = None) -> None:
        """Fire-and-forget publish from sync code / callbacks."""
        asyncio.get_event_loop().create_task(self.publish(topic, payload))
