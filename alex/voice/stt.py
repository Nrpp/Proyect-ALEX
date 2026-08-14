"""
Speech-to-text using faster-whisper (CTranslate2 port of OpenAI Whisper).

Chosen for the Pi because it runs fully offline/local, and with a
"small"/"tiny" model + int8 quantization it transcribes short utterances in
a few seconds on a Raspberry Pi 4 CPU - good enough for a voice assistant
turn without needing to ship audio to any cloud service.
"""
from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)


class SpeechToText:
    def __init__(self, model_size: str = "small", language: str = "es"):
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_size, device="cpu", compute_type="int8")
        self._language = language
        log.info("STT ready (faster-whisper, model=%s, lang=%s, cpu/int8)", model_size, language)

    def transcribe(self, pcm_int16: np.ndarray) -> str:
        audio = pcm_int16.astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(
            audio, language=self._language, beam_size=1, vad_filter=True
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        log.info("STT result: %r", text)
        return text
