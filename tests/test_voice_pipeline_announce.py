from __future__ import annotations

import asyncio

import pytest

# alex/voice/pipeline.py imports numpy/sounddevice/etc unconditionally (see
# requirements-voice.txt) - those are only installed where voice is actually
# used (voice_enabled defaults to false), not in a plain dev/test install.
# Skip this whole module rather than erroring the entire test collection
# when they're absent.
pytest.importorskip("numpy", reason="requirements-voice.txt not installed")

from alex.voice.pipeline import ANNOUNCE_SOURCES, VoicePipeline  # noqa: E402

pytestmark = pytest.mark.asyncio


class _FakeNotification:
    def __init__(self, source: str, body: str):
        self.source = source
        self.body = body


def _bare_pipeline() -> VoicePipeline:
    # VoicePipeline.__init__ touches real mic/wakeword/STT/TTS hardware and
    # model files, none of which exist in CI - _on_notification is pure
    # queueing logic that doesn't need any of that, so build an uninitialized
    # instance and set only what it touches.
    pipeline = object.__new__(VoicePipeline)
    pipeline._announce_queue = asyncio.Queue()
    return pipeline


async def test_daily_briefing_is_an_announce_source():
    assert "daily_briefing" in ANNOUNCE_SOURCES


async def test_on_notification_queues_allowlisted_source():
    pipeline = _bare_pipeline()
    pipeline._on_notification(_FakeNotification(source="daily_briefing", body="Buenos dias..."))
    assert pipeline._announce_queue.get_nowait() == "Buenos dias..."


async def test_on_notification_ignores_non_allowlisted_source():
    pipeline = _bare_pipeline()
    pipeline._on_notification(_FakeNotification(source="reminders", body="Recordatorio"))
    assert pipeline._announce_queue.empty()


async def test_on_notification_ignores_alex_confirmation_source():
    pipeline = _bare_pipeline()
    pipeline._on_notification(_FakeNotification(source="alex", body="Confirmacion necesaria"))
    assert pipeline._announce_queue.empty()
