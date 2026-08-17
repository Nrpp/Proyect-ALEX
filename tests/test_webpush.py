from __future__ import annotations

import pytest

import alex.notifications.push as push_module
from alex.notifications.models import Notification
from alex.notifications.push import PushSubscriptionStore, WebPushSender
from pywebpush import WebPushException

pytestmark = pytest.mark.asyncio


async def test_add_list_remove_round_trip(db):
    store = PushSubscriptionStore(db)
    await store.add("https://push.example.com/a", "p256dh-a", "auth-a")
    await store.add("https://push.example.com/b", "p256dh-b", "auth-b")

    subs = await store.list_all()
    assert {s["endpoint"] for s in subs} == {"https://push.example.com/a", "https://push.example.com/b"}

    await store.remove("https://push.example.com/a")
    subs = await store.list_all()
    assert [s["endpoint"] for s in subs] == ["https://push.example.com/b"]


async def test_adding_same_endpoint_twice_updates_keys_not_duplicates(db):
    store = PushSubscriptionStore(db)
    await store.add("https://push.example.com/a", "old-p256dh", "old-auth")
    await store.add("https://push.example.com/a", "new-p256dh", "new-auth")

    subs = await store.list_all()
    assert len(subs) == 1
    assert subs[0]["p256dh"] == "new-p256dh"
    assert subs[0]["auth"] == "new-auth"


async def test_is_configured_requires_both_private_key_and_contact_email(db):
    store = PushSubscriptionStore(db)
    assert WebPushSender(store, "", "").is_configured is False
    assert WebPushSender(store, "priv", "").is_configured is False
    assert WebPushSender(store, "", "me@example.com").is_configured is False
    assert WebPushSender(store, "priv", "me@example.com").is_configured is True


async def test_send_to_all_is_noop_when_not_configured(db, monkeypatch):
    store = PushSubscriptionStore(db)
    await store.add("https://push.example.com/a", "p256dh", "auth")
    sender = WebPushSender(store, "", "")

    called = False

    async def fake_webpush_async(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(push_module, "webpush_async", fake_webpush_async)
    await sender.send_to_all(Notification(id="1", source="alex", title="Hola", body="mundo"))
    assert called is False


async def test_send_to_all_is_noop_with_no_subscriptions(db, monkeypatch):
    store = PushSubscriptionStore(db)
    sender = WebPushSender(store, "priv", "me@example.com")

    called = False

    async def fake_webpush_async(**kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(push_module, "webpush_async", fake_webpush_async)
    await sender.send_to_all(Notification(id="1", source="alex", title="Hola", body="mundo"))
    assert called is False


async def test_send_to_all_calls_webpush_for_every_subscription(db, monkeypatch):
    store = PushSubscriptionStore(db)
    await store.add("https://push.example.com/a", "p256dh-a", "auth-a")
    await store.add("https://push.example.com/b", "p256dh-b", "auth-b")
    sender = WebPushSender(store, "priv-key", "me@example.com")

    calls = []

    async def fake_webpush_async(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(push_module, "webpush_async", fake_webpush_async)
    await sender.send_to_all(Notification(id="1", source="alex", title="Riego", body="Terminado", priority=2))

    assert len(calls) == 2
    endpoints = {c["subscription_info"]["endpoint"] for c in calls}
    assert endpoints == {"https://push.example.com/a", "https://push.example.com/b"}
    assert calls[0]["vapid_private_key"] == "priv-key"
    assert calls[0]["vapid_claims"] == {"sub": "mailto:me@example.com"}
    assert '"title": "Riego"' in calls[0]["data"]
    assert '"priority": 2' in calls[0]["data"]


async def test_send_to_all_removes_subscription_on_410_gone(db, monkeypatch):
    store = PushSubscriptionStore(db)
    await store.add("https://push.example.com/a", "p256dh-a", "auth-a")
    sender = WebPushSender(store, "priv-key", "me@example.com")

    class FakeResponse:
        status = 410

    async def failing_webpush_async(**kwargs):
        raise WebPushException("gone", response=FakeResponse())

    monkeypatch.setattr(push_module, "webpush_async", failing_webpush_async)
    await sender.send_to_all(Notification(id="1", source="alex", title="Hola", body="mundo"))

    assert await store.list_all() == []


async def test_send_to_all_keeps_subscription_on_transient_error(db, monkeypatch):
    store = PushSubscriptionStore(db)
    await store.add("https://push.example.com/a", "p256dh-a", "auth-a")
    sender = WebPushSender(store, "priv-key", "me@example.com")

    class FakeResponse:
        status = 503

    async def failing_webpush_async(**kwargs):
        raise WebPushException("temporarily unavailable", response=FakeResponse())

    monkeypatch.setattr(push_module, "webpush_async", failing_webpush_async)
    await sender.send_to_all(Notification(id="1", source="alex", title="Hola", body="mundo"))

    subs = await store.list_all()
    assert len(subs) == 1
    assert subs[0]["endpoint"] == "https://push.example.com/a"
