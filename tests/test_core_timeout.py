from __future__ import annotations

import asyncio
import time

import pytest

from alex.ai.base import AIProvider, AIResponse, ToolCall
from alex.config import Settings
from alex.core.core import ALEXCore

pytestmark = pytest.mark.asyncio


class SlowProvider(AIProvider):
    name = "slow"

    def __init__(self, delay_seconds: float):
        self._delay = delay_seconds

    async def complete(self, messages, *, system, tools=None, max_tokens=1024, temperature=0.4):
        await asyncio.sleep(self._delay)
        return AIResponse(content="should never be returned")

    async def health_check(self) -> bool:
        return True


class LoopingProvider(AIProvider):
    """Every hop is individually fast but always requests a tool call, so the
    AI<->tool loop never finishes on its own - several quick hops adding up
    past the overall turn timeout, without any single call being slow."""

    name = "looping"

    def __init__(self, hop_delay_seconds: float):
        self._hop_delay = hop_delay_seconds
        self.calls = 0

    async def complete(self, messages, *, system, tools=None, max_tokens=1024, temperature=0.4):
        self.calls += 1
        await asyncio.sleep(self._hop_delay)
        return AIResponse(
            content=None,
            tool_calls=[ToolCall(id=str(self.calls), name="get_current_time", arguments={})],
        )

    async def health_check(self) -> bool:
        return True


async def test_slow_ai_provider_times_out_instead_of_hanging(tmp_path):
    settings = Settings(
        db_path=tmp_path / "test_alex.db",
        log_dir=tmp_path / "logs",
        data_dir=tmp_path,
        ai_request_timeout_seconds=1,
        enabled_plugins=[],
    )

    core = ALEXCore(settings)
    core.ai = SlowProvider(delay_seconds=5)
    await core.start()
    try:
        start = time.monotonic()
        result = await core.handle_user_message("hola", channel="test")
        elapsed = time.monotonic() - start

        assert elapsed < 3, f"handle_user_message should time out quickly, took {elapsed:.1f}s"
        assert "tardando demasiado" in result["reply"]
        assert result["pending_action_id"] is None
    finally:
        await core.shutdown()


async def test_many_fast_hops_are_bounded_by_the_overall_turn_timeout(tmp_path):
    """Regression test: a model that keeps calling tools in a loop, each hop
    individually well under ai_request_timeout_seconds, could previously
    still hang the whole turn past any reasonable total latency."""
    settings = Settings(
        db_path=tmp_path / "test_alex.db",
        log_dir=tmp_path / "logs",
        data_dir=tmp_path,
        ai_request_timeout_seconds=45,  # generous per-hop budget
        ai_turn_timeout_seconds=2,      # tight overall budget
        ai_max_tool_hops=6,
        enabled_plugins=[],
    )

    core = ALEXCore(settings)
    core.ai = LoopingProvider(hop_delay_seconds=0.5)  # 6 hops * 0.5s = 3s > 2s turn budget
    await core.start()
    try:
        start = time.monotonic()
        result = await core.handle_user_message("que hora es", channel="test")
        elapsed = time.monotonic() - start

        assert elapsed < 4, f"overall turn timeout should have cut this off around 2s, took {elapsed:.1f}s"
        assert core.ai.calls < 6, "should have been aborted before exhausting all hops"
        assert "tardando demasiado" in result["reply"]
    finally:
        await core.shutdown()
