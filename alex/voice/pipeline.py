"""
VoicePipeline - ties wake word, STT, ALEX Core and TTS into the always-on
voice loop described in the project brief:

  passive listening (wake word only, local) --"Alex"--> record utterance
  --> STT (local) --> ALEXCore.handle_user_message (AI/tools/memory)
  --> TTS (local) --> speak reply --> short follow-up window (no wake word
  needed) --> back to passive listening.

No audio is ever streamed off the device. Only the wake-word engine and STT
run continuously/on-utterance locally; the text of what you said is what
(optionally) reaches a remote AI provider, exactly like typing into the API
would.
"""
from __future__ import annotations

import asyncio
import logging
import time

import numpy as np

from alex.config import Settings
from alex.core.core import ALEXCore
from alex.voice.audio_io import FRAME_MS, MicStream, play_pcm
from alex.voice.stt import SpeechToText
from alex.voice.tts import TextToSpeech
from alex.voice.wakeword import WakeWordDetector

log = logging.getLogger(__name__)

# Tuning constants for the simple energy-based end-of-utterance detector.
# Raspberry Pi mics vary a lot - if ALEX cuts you off or never stops
# "listening", adjust SILENCE_AMPLITUDE_THRESHOLD (see docs/INSTALL_RASPBERRY_PI.md).
SILENCE_AMPLITUDE_THRESHOLD = 300
SILENCE_END_MS = 900
MIN_UTTERANCE_MS = 400
MAX_UTTERANCE_MS = 15_000


def _is_silence(frame: np.ndarray) -> bool:
    return float(np.abs(frame).mean()) < SILENCE_AMPLITUDE_THRESHOLD


class VoicePipeline:
    def __init__(self, core: ALEXCore, settings: Settings):
        self._core = core
        self._settings = settings
        self._mic = MicStream(settings.mic_device)
        self._wakeword = WakeWordDetector(
            model_path=settings.wakeword_model_path,
            model_name=settings.wakeword_name,
            threshold=settings.wakeword_threshold,
        )
        self._stt = SpeechToText(model_size=settings.stt_model_size, language=settings.stt_language)
        self._tts = TextToSpeech(voice_name=settings.tts_voice, model_dir=settings.tts_model_dir)
        self._running = False

    async def run(self) -> None:
        self._running = True
        self._mic.start()
        log.info("Voice pipeline active - listening passively for the wake word")
        state = "passive"
        utterance_frames: list[np.ndarray] = []
        silence_ms = 0
        follow_up_started = 0.0

        try:
            async for frame in self._mic.frames():
                if not self._running:
                    break

                if state == "passive":
                    if self._wakeword.process(frame):
                        state = "recording"
                        utterance_frames = []
                        silence_ms = 0
                        await self._speak("Dime.")

                elif state == "recording":
                    utterance_frames.append(frame)
                    silence_ms = silence_ms + FRAME_MS if _is_silence(frame) else 0
                    total_ms = len(utterance_frames) * FRAME_MS
                    ended = (silence_ms >= SILENCE_END_MS and total_ms >= MIN_UTTERANCE_MS)
                    if ended or total_ms >= MAX_UTTERANCE_MS:
                        pcm = np.concatenate(utterance_frames)
                        utterance_frames = []
                        state = await self._process_utterance(pcm)
                        if state == "follow_up":
                            follow_up_started = time.monotonic()
                        else:
                            self._wakeword.reset()

                elif state == "follow_up":
                    if not _is_silence(frame):
                        state = "recording"
                        utterance_frames = [frame]
                        silence_ms = 0
                    elif time.monotonic() - follow_up_started > self._settings.conversation_follow_up_seconds:
                        state = "passive"
                        self._wakeword.reset()
                        log.info("Follow-up window closed - back to passive listening")
        finally:
            self._mic.stop()

    def stop(self) -> None:
        self._running = False

    async def _process_utterance(self, pcm: np.ndarray) -> str:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, self._stt.transcribe, pcm)
        if not text:
            return "passive"

        result = await self._core.handle_user_message(text, channel="voice")
        reply = result.get("reply") or ""
        if reply:
            await self._speak(reply)
        return "follow_up" if reply else "passive"

    async def _speak(self, text: str) -> None:
        loop = asyncio.get_event_loop()
        pcm = await loop.run_in_executor(None, self._tts.synthesize, text)
        if pcm.size:
            await loop.run_in_executor(None, play_pcm, pcm, self._tts.sample_rate)
