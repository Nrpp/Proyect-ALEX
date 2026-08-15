from __future__ import annotations

import pytest

from alex.ai.base import AIProvider, AIResponse, ToolCall
from alex.config import Settings
from alex.core.core import ALEXCore
from alex.server.ws import ConnectionManager
from alex.tools.base import PermissionLevel, Tool, ToolResult


class ConfirmTool(Tool):
    name = "delete_everything"
    description = "Borra todo (peligroso, solo para el test)"
    permission_level = PermissionLevel.CONFIRM

    async def run(self, **kwargs) -> ToolResult:
        return ToolResult(success=True, content="Borrado.")


class WantsToDeleteProvider(AIProvider):
    name = "wants-to-delete"

    def __init__(self):
        self.calls = 0

    async def complete(self, messages, *, system, tools=None, max_tokens=1024, temperature=0.4):
        self.calls += 1
        return AIResponse(
            content=None,
            tool_calls=[ToolCall(id=str(self.calls), name="delete_everything", arguments={})],
        )

    async def health_check(self) -> bool:
        return True


class FakeWebSocket:
    """Stands in for a connected client - just records what it was sent."""

    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, message: dict) -> None:
        self.sent.append(message)


async def _make_core(tmp_path) -> ALEXCore:
    settings = Settings(
        db_path=tmp_path / "test_alex.db",
        log_dir=tmp_path / "logs",
        data_dir=tmp_path,
        enabled_plugins=[],
    )
    core = ALEXCore(settings)
    core.ai = WantsToDeleteProvider()
    await core.start()
    core.tools.register(ConfirmTool())
    return core


@pytest.mark.asyncio
async def test_resolving_via_rest_style_call_broadcasts_chat_reply_to_connected_clients(tmp_path):
    """Regression: confirming/cancelling through the notification button goes
    through POST /actions/{id}/confirm -> core.resolve_pending_action()
    directly, with no WebSocket request of its own to reply on. Before this
    fix, that path only ever produced a separate "notification" toast and
    the chat window never learned the outcome. ConnectionManager must
    broadcast it as a chat.reply to every connected client instead."""
    core = await _make_core(tmp_path)
    try:
        connections = ConnectionManager(core)
        ws = FakeWebSocket()
        connections._clients.add(ws)

        turn = await core.handle_user_message("borra todo", channel="test")
        action_id = turn["pending_action_id"]
        assert action_id is not None
        sent_before_resolve = len(ws.sent)

        # Simulate the notification button: resolve directly, no chat text,
        # no WebSocket message from this "client" at all.
        result = await core.resolve_pending_action(action_id, approved=True)
        assert result["success"] is True

        new_messages = ws.sent[sent_before_resolve:]
        chat_replies = [m for m in new_messages if m.get("type") == "chat.reply"]
        assert len(chat_replies) == 1, f"expected one broadcast chat.reply, got {new_messages}"
        assert "Hecho" in chat_replies[0]["reply"]
        assert chat_replies[0]["conversation_id"] == turn["conversation_id"]
    finally:
        await core.shutdown()


@pytest.mark.asyncio
async def test_cancelling_via_rest_style_call_also_broadcasts_chat_reply(tmp_path):
    core = await _make_core(tmp_path)
    try:
        connections = ConnectionManager(core)
        ws = FakeWebSocket()
        connections._clients.add(ws)

        turn = await core.handle_user_message("borra todo", channel="test")
        action_id = turn["pending_action_id"]
        sent_before_resolve = len(ws.sent)

        await core.resolve_pending_action(action_id, approved=False)

        new_messages = ws.sent[sent_before_resolve:]
        chat_replies = [m for m in new_messages if m.get("type") == "chat.reply"]
        assert len(chat_replies) == 1
        assert "cancelado" in chat_replies[0]["reply"]
    finally:
        await core.shutdown()


@pytest.mark.asyncio
async def test_normal_chat_turn_still_broadcasts_exactly_once(tmp_path):
    """Regression: chat.message replies used to be sent directly to the
    caller AND (after wiring the broadcast) would double up if not for
    removing the old direct send in alex/server/ws.py - make sure a plain
    chat turn (no confirmation involved) reaches connected clients exactly
    once, not zero or two times."""
    settings = Settings(
        db_path=tmp_path / "test_alex.db",
        log_dir=tmp_path / "logs",
        data_dir=tmp_path,
        enabled_plugins=[],
    )
    core = ALEXCore(settings)

    class SaysHiProvider(AIProvider):
        name = "says-hi"

        async def complete(self, messages, *, system, tools=None, max_tokens=1024, temperature=0.4):
            return AIResponse(content="hola")

        async def health_check(self) -> bool:
            return True

    core.ai = SaysHiProvider()
    await core.start()
    try:
        connections = ConnectionManager(core)
        ws = FakeWebSocket()
        connections._clients.add(ws)

        await core.handle_user_message("hola", channel="test")

        chat_replies = [m for m in ws.sent if m.get("type") == "chat.reply"]
        assert len(chat_replies) == 1, f"expected exactly one chat.reply, got {ws.sent}"
        assert chat_replies[0]["reply"] == "hola"
    finally:
        await core.shutdown()
