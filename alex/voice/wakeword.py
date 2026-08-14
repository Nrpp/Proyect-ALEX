"""
Wake word detection using openWakeWord (https://github.com/dscripka/openWakeWord).

Chosen because it runs comfortably on a Raspberry Pi 4 CPU (small ONNX
models, tens of ms per 80ms frame), is fully local/offline, and is
straightforward to extend with a custom keyword.

IMPORTANT - "Alex" is not one of openWakeWord's bundled pretrained keywords
(it ships "alexa", "hey_jarvis", "hey_mycroft", "hey_rhasspy", etc). To
actually wake on the word "Alex" you need a model trained for it:

  1. Easiest: use openWakeWord's free Google Colab training notebook
     (linked from the project README) to train "alex.onnx" from synthetic
     TTS samples - takes ~20-30 minutes, no GPU needed on your side.
  2. Drop the resulting file at data/voice_models/wakeword/alex.onnx
  3. Set ALEX_WAKEWORD_MODEL_PATH=data/voice_models/wakeword/alex.onnx

Until you do that, ALEX_WAKEWORD_NAME defaults to "hey_jarvis" (a bundled
model) so the voice pipeline is fully testable out of the box - just say
"Hey Jarvis" instead of "Alex" until your custom model is ready. This
abstraction (WakeWordDetector) is exactly what lets you swap the model
later without touching any other voice code.
"""
from __future__ import annotations

import logging

import numpy as np

log = logging.getLogger(__name__)


class WakeWordDetector:
    def __init__(self, *, model_path: str = "", model_name: str = "hey_jarvis", threshold: float = 0.5):
        from openwakeword.model import Model

        wakeword_models = [model_path] if model_path else [model_name]
        self._model = Model(wakeword_models=wakeword_models, inference_framework="onnx")
        self._threshold = threshold
        self._label = _basename(model_path) if model_path else model_name
        log.info("Wake word detector ready (listening for '%s', threshold=%.2f)", self._label, threshold)

    def process(self, frame: np.ndarray) -> bool:
        """Feed one 80ms int16 frame (1280 samples @16kHz). Returns True if the wake word fired."""
        predictions = self._model.predict(frame)
        score = predictions.get(self._label, 0.0)
        if score >= self._threshold:
            log.info("Wake word detected (score=%.2f)", score)
            self._model.reset()
            return True
        return False

    def reset(self) -> None:
        self._model.reset()


def _basename(path: str) -> str:
    import os

    name = os.path.basename(path)
    return name.rsplit(".", 1)[0] if "." in name else name
