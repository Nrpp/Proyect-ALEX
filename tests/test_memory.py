from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


async def test_conversation_round_trip(memory):
    conv_id = await memory.start_conversation(channel="test")
    await memory.add_message(conv_id, "user", "Hola Alex")
    await memory.add_message(conv_id, "assistant", "Hola Nicolas")

    messages = await memory.get_recent_messages(conv_id)
    assert [m.role for m in messages] == ["user", "assistant"]
    assert messages[0].content == "Hola Alex"


async def test_remember_and_recall(memory):
    await memory.remember("A Nicolas le gusta el senderismo los domingos", tags=["hobbies"])
    await memory.remember("El proyecto ALEX usa SQLite para memoria persistente", project="alex")

    results = await memory.recall("senderismo")
    assert len(results) == 1
    assert "senderismo" in results[0].content

    results_project = await memory.recall("SQLite", project="alex")
    assert len(results_project) == 1


async def test_forget_memory(memory):
    memory_id = await memory.remember("Recuerdo temporal de prueba")
    assert await memory.forget(memory_id) is True
    assert await memory.forget(memory_id) is False  # already gone


async def test_facts_and_preferences(memory):
    await memory.set_fact("cumpleanos", "1998-05-02", category="personal")
    fact = await memory.get_fact("cumpleanos")
    assert fact is not None
    assert fact.value == "1998-05-02"

    await memory.set_preference("tono", "cercano")
    assert await memory.get_preference("tono") == "cercano"
    assert await memory.get_preference("no_existe", default="x") == "x"


async def test_reminders(memory):
    reminder_id = await memory.add_reminder("Examen de calculo", "2026-08-20T09:00:00")
    due = await memory.list_due_reminders("2026-08-21T00:00:00")
    assert len(due) == 1
    assert due[0]["id"] == reminder_id

    not_due = await memory.list_due_reminders("2026-08-19T00:00:00")
    assert not_due == []

    await memory.mark_reminder_fired(reminder_id)
    assert await memory.list_due_reminders("2026-08-21T00:00:00") == []
