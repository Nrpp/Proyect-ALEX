from __future__ import annotations

import asyncio

import pytest

from alex.config import Settings
from alex.core.core import ALEXCore

pytestmark = pytest.mark.asyncio


async def test_scheduled_async_callback_actually_runs(tmp_path):
    """
    Regression test: plugins register background checks as
    `ctx.schedule_interval(lambda: self._check(ctx), ...)`. A bare lambda
    is not itself a coroutine function, so APScheduler's AsyncIOExecutor
    used to run it in a worker thread and silently discard the resulting
    coroutine unawaited - the check logic never actually ran, with no
    error, just a "coroutine was never awaited" warning at GC time. This
    would have caught it: without the fix in ALEXCore._schedule_interval,
    `ran.is_set()` stays False.
    """
    settings = Settings(
        db_path=tmp_path / "test_alex.db",
        log_dir=tmp_path / "logs",
        data_dir=tmp_path,
        enabled_plugins=[],
    )
    core = ALEXCore(settings)
    await core.start()
    try:
        ran = asyncio.Event()

        async def check() -> None:
            ran.set()

        core._schedule_interval(lambda: check(), 0.1, "test_job")

        await asyncio.wait_for(ran.wait(), timeout=3)
        assert ran.is_set()
    finally:
        await core.shutdown()
