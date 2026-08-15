"""
AnyAPI provider (https://anyapi.ai) - OpenAI-compatible chat completions API
giving access to 400+ models from many vendors behind one key, with model
ids in "provider/model-name" format (e.g. "openai/gpt-4o-mini",
"anthropic/claude-3.5-sonnet"). Same shape as OpenRouter - another thin
wrapper over the shared OpenAICompatibleProvider.
"""
from __future__ import annotations

from alex.ai.openai_compatible_provider import OpenAICompatibleProvider


class AnyAPIProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str, base_url: str, model: str):
        super().__init__(name="anyapi", api_key=api_key, base_url=base_url, model=model)
