from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from alex.config import Settings
from alex.core.core import ALEXCore
from alex.server.app import create_app


def _make_client(tmp_path) -> tuple[TestClient, ALEXCore]:
    settings = Settings(
        db_path=tmp_path / "test_alex.db",
        log_dir=tmp_path / "logs",
        data_dir=tmp_path,
        enabled_plugins=[],
    )
    app = create_app(settings)
    client = TestClient(app)
    client.__enter__()
    return client, app.state.core


def test_get_reminders_returns_pending_ones_ordered_by_due_at(tmp_path):
    client, core = _make_client(tmp_path)
    try:
        asyncio.run(core.memory.add_reminder("Llamar al medico", "2026-09-01T09:00:00"))
        asyncio.run(core.memory.add_reminder("Examen de calculo", "2026-08-20T09:00:00"))

        response = client.get("/reminders")

        assert response.status_code == 200
        reminders = response.json()
        assert len(reminders) == 2
        assert reminders[0]["due_at"] == "2026-08-20T09:00:00"
        assert reminders[0]["text"] == "Examen de calculo"
        assert reminders[1]["due_at"] == "2026-09-01T09:00:00"
    finally:
        client.__exit__(None, None, None)


def test_delete_reminder_cancels_it_and_removes_it_from_the_list(tmp_path):
    client, core = _make_client(tmp_path)
    try:
        reminder_id = asyncio.run(core.memory.add_reminder("Prueba", "2026-09-01T09:00:00"))

        response = client.delete(f"/reminders/{reminder_id}")

        assert response.status_code == 200
        assert response.json() == {"success": True}
        assert client.get("/reminders").json() == []
    finally:
        client.__exit__(None, None, None)


def test_delete_unknown_reminder_reports_failure_without_erroring(tmp_path):
    client, _core = _make_client(tmp_path)
    try:
        response = client.delete("/reminders/does-not-exist")

        assert response.status_code == 200
        assert response.json() == {"success": False}
    finally:
        client.__exit__(None, None, None)
