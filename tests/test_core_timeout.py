from __future__ import annotations

import asyncio
import time

import pytest

from alex.ai.base import AIProvider, AIResponse
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
