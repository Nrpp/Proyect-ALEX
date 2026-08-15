from __future__ import annotations

import pytest

from alex.ai.base import AIProvider, AIResponse, ToolCall
from alex.config import Settings
from alex.core.core import ALEXCore, _classify_confirmation_response
from alex.tools.base import PermissionLevel, Tool, ToolResult


class ConfirmTool(Tool):
    name = "delete_everything"
    description = "Borra todo (peligroso, solo para el test)"
    permission_level = PermissionLevel.CONFIRM

    def __init__(self):
        self.executed = False

    async def run(self, **kwargs) -> ToolResult:
        self.executed = True
        return ToolResult(success=True, content="Borrado.")


class WantsToDeleteProvider(AIProvider):
    """Always asks to call the CONFIRM-gated tool. Used to drive the core
    into a pending-confirmation state without a real plugin/tool."""

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


def test_classify_confirmation_response_is_exact_match_only():
    assert _classify_confirmation_response("si") is True
    assert _classify_confirmation_response(" Sí. ") is True
    assert _classify_confirmation_response("no") is False
    assert _classify_confirmation_response("No.") is False
    # Must not match on substrings - this was the whole point of the fix.
    assert _classify_confirmation_response("no lo puedes ver?") is None
    assert _classify_confirmation_response("sin duda hazlo despues") is None
    assert _classify_confirmation_response("cuanto cuesta") is None


async def _make_core(tmp_path) -> tuple[ALEXCore, ConfirmTool]:
    settings = Settings(
        db_path=tmp_path / "test_alex.db",
        log_dir=tmp_path / "logs",
        data_dir=tmp_path,
        enabled_plugins=[],
    )
    core = ALEXCore(settings)
    provider = WantsToDeleteProvider()
    core.ai = provider
    await core.start()
    tool = ConfirmTool()
    core.tools.register(tool)
    return core, tool


@pytest.mark.asyncio
async def test_saying_si_in_chat_resolves_the_pending_confirmation(tmp_path):
    core, tool = await _make_core(tmp_path)
    try:
        first = await core.handle_user_message("borra todo", channel="test")
        assert first["pending_action_id"] is not None
        assert not tool.executed

        calls_before = core.ai.calls
        second = await core.handle_user_message("si", channel="test")

        # Resolved by the deterministic classifier, not a fresh AI call/loop.
        assert core.ai.calls == calls_before
        assert tool.executed
        assert "Hecho" in second["reply"]
        assert second["pending_action_id"] is None
    finally:
        await core.shutdown()


@pytest.mark.asyncio
async def test_saying_no_in_chat_cancels_the_pending_confirmation(tmp_path):
    core, tool = await _make_core(tmp_path)
    try:
        first = await core.handle_user_message("borra todo", channel="test")
        assert first["pending_action_id"] is not None

        calls_before = core.ai.calls
        second = await core.handle_user_message("no", channel="test")

        assert core.ai.calls == calls_before
        assert not tool.executed
        assert "cancelado" in second["reply"]
    finally:
        await core.shutdown()


@pytest.mark.asyncio
async def test_ambiguous_message_does_not_falsely_resolve_and_falls_through_to_ai(tmp_path):
    core, tool = await _make_core(tmp_path)
    try:
        first = await core.handle_user_message("borra todo", channel="test")
        assert first["pending_action_id"] is not None

        calls_before = core.ai.calls
        # Contains "no" as a substring but is not a yes/no answer - must not
        # be misread as cancellation, and must go back through the AI
        # (which in this fake provider just re-requests the same tool call,
        # re-raising a fresh pending confirmation rather than executing).
        second = await core.handle_user_message("no lo puedes ver?", channel="test")

        assert core.ai.calls == calls_before + 1
        assert not tool.executed
        assert second["pending_action_id"] is not None
    finally:
        await core.shutdown()


@pytest.mark.asyncio
async def test_resolve_pending_action_does_not_double_write_memory(tmp_path):
    """Regression: resolve_pending_action() persists the outcome message to
    the tracked conversation itself; handle_user_message() must not add it
    again, or every chat-resolved confirmation would appear twice in history."""
    core, tool = await _make_core(tmp_path)
    try:
        first = await core.handle_user_message("borra todo", channel="test")
        conversation_id = first["conversation_id"]

        await core.handle_user_message("si", channel="test")

        context = await core.memory.build_context_bundle(conversation_id, "")
        done_messages = [m for m in context["recent_messages"] if m.content.startswith("Hecho")]
        assert len(done_messages) == 1, f"expected exactly one 'Hecho' message, got {done_messages}"
    finally:
        await core.shutdown()
