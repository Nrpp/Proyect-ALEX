"""
Microphone capture and speaker playback, isolated from the rest of the
voice pipeline so wakeword.py / stt.py / tts.py only ever deal with numpy
PCM arrays, never with sounddevice directly.

Everything here runs fully on-device - audio never leaves the Raspberry Pi
during passive listening. Only the short utterance captured AFTER the wake
word fires is turned into text (locally, via faster-whisper), and only that
text (not audio) may leave the box if a remote AI provider is configured.
"""
from __future__ import annotations

import asyncio
import logging
import queue

import numpy as np

log = logging.getLogger(__name__)

SAMPLE_RATE = 16000
FRAME_MS = 80
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000  # 1280 samples/frame - openWakeWord's expected chunk size


class MicStream:
    """Continuous 16kHz mono int16 microphone stream, frame-by-frame, as an async generator."""

    def __init__(self, device: str | int | None = None):
        self._device = device
        self._raw_queue: queue.Queue[np.ndarray] = queue.Queue()
        self._stream = None

    def _callback(self, indata, frames, time_info, status) -> None:
        if status:
            log.debug("Mic stream status: %s", status)
        self._raw_queue.put(indata[:, 0].copy())

    def start(self) -> None:
        import sounddevice as sd

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            device=self._device,
            callback=self._callback,
        )
        self._stream.start()
        log.info("Microphone stream started (device=%s)", self._device or "default")

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None

    async def frames(self):
        """Async generator yielding int16 numpy frames of FRAME_SAMPLES length."""
        loop = asyncio.get_event_loop()
        while True:
            frame = await loop.run_in_executor(None, self._raw_queue.get)
            yield frame


def play_pcm(pcm: np.ndarray, sample_rate: int) -> None:
    """Blocking playback of int16 PCM audio through the default output device."""
    import sounddevice as sd

    sd.play(pcm, samplerate=sample_rate)
    sd.wait()
