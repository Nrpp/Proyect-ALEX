"""
Text-to-speech using Piper (https://github.com/rhasspy/piper).

Chosen for the Pi because it's a small, fast neural TTS engine written for
exactly this kind of hardware - real-time synthesis on a Raspberry Pi 4 CPU,
fully offline, with natural-sounding Spanish/English voices.

Voice models are NOT bundled with this repo (they're tens of MB of ONNX
weights). Download the voice referenced by ALEX_TTS_VOICE from
https://huggingface.co/rhasspy/piper-voices into ALEX_TTS_MODEL_DIR - see
docs/INSTALL_RASPBERRY_PI.md for the exact command.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from alex.core.errors import VoiceError

log = logging.getLogger(__name__)


class TextToSpeech:
    def __init__(self, voice_name: str, model_dir: Path):
        from piper import PiperVoice

        onnx_path = model_dir / f"{voice_name}.onnx"
        config_path = model_dir / f"{voice_name}.onnx.json"
        if not onnx_path.exists():
            raise VoiceError(
                f"No se encontro el modelo de voz Piper '{onnx_path}'. "
                f"Descargalo (ver docs/INSTALL_RASPBERRY_PI.md) antes de activar la voz."
            )
        self._voice = PiperVoice.load(str(onnx_path), config_path=str(config_path) if config_path.exists() else None)
        self.sample_rate = self._voice.config.sample_rate
        log.info("TTS ready (Piper voice=%s, sample_rate=%d)", voice_name, self.sample_rate)

    def synthesize(self, text: str) -> np.ndarray:
        """Returns int16 mono PCM audio for the given text."""
        chunks: list[np.ndarray] = []
        for audio_bytes in self._voice.synthesize_stream_raw(text):
            chunks.append(np.frombuffer(audio_bytes, dtype=np.int16))
        if not chunks:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(chunks)
