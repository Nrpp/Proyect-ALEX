"""
NVIDIA NIM provider (https://build.nvidia.com) - OpenAI-compatible chat
completions API. This is the default provider because NVIDIA offers a free
tier of hosted inference, which is a good fit for a Raspberry Pi 4 that
cannot realistically run a strong LLM locally.

Just a thin wrapper over the shared OpenAICompatibleProvider - see
openai_compatible_provider.py for the actual request/response handling.
"""
from __future__ import annotations

from alex.ai.openai_compatible_provider import OpenAICompatibleProvider


class NvidiaProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str, base_url: str, model: str):
        super().__init__(name="nvidia", api_key=api_key, base_url=base_url, model=model)
