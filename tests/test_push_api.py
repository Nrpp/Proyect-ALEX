from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from alex.config import Settings
from alex.core.core import ALEXCore
from alex.server.app import create_app


def _make_client(tmp_path, **settings_kwargs) -> tuple[TestClient, ALEXCore]:
    settings = Settings(
        db_path=tmp_path / "test_alex.db",
        log_dir=tmp_path / "logs",
        data_dir=tmp_path,
        enabled_plugins=[],
        **settings_kwargs,
    )
    app = create_app(settings)
    client = TestClient(app)
    client.__enter__()
    return client, app.state.core


def test_vapid_public_key_reports_unconfigured_by_default(tmp_path):
    client, _core = _make_client(tmp_path)
    try:
        response = client.get("/push/vapid_public_key")
        assert response.status_code == 200
        assert response.json() == {"configured": False, "public_key": ""}
    finally:
        client.__exit__(None, None, None)


def test_vapid_public_key_returns_the_configured_key(tmp_path):
    client, _core = _make_client(tmp_path, vapid_public_key="test-public-key")
    try:
        response = client.get("/push/vapid_public_key")
        assert response.json() == {"configured": True, "public_key": "test-public-key"}
    finally:
        client.__exit__(None, None, None)


def test_subscribe_stores_the_subscription(tmp_path):
    client, core = _make_client(tmp_path)
    try:
        response = client.post(
            "/push/subscribe",
            json={"endpoint": "https://push.example.com/a", "keys": {"p256dh": "p256dh-val", "auth": "auth-val"}},
        )
        assert response.status_code == 200
        assert response.json() == {"success": True}

        subs = asyncio.run(core.push_subscriptions.list_all())
        assert len(subs) == 1
        assert subs[0]["endpoint"] == "https://push.example.com/a"
        assert subs[0]["p256dh"] == "p256dh-val"
        assert subs[0]["auth"] == "auth-val"
    finally:
        client.__exit__(None, None, None)


def test_unsubscribe_removes_the_subscription(tmp_path):
    client, core = _make_client(tmp_path)
    try:
        client.post(
            "/push/subscribe",
            json={"endpoint": "https://push.example.com/a", "keys": {"p256dh": "x", "auth": "y"}},
        )

        response = client.post("/push/unsubscribe", json={"endpoint": "https://push.example.com/a"})

        assert response.status_code == 200
        assert response.json() == {"success": True}
        assert asyncio.run(core.push_subscriptions.list_all()) == []
    finally:
        client.__exit__(None, None, None)
