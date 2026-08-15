"""
OpenRouter provider (https://openrouter.ai) - OpenAI-compatible chat
completions API that proxies to many different model vendors behind one
key. Useful if you want a wider choice of models than NVIDIA NIM offers,
including several free-tier models.

Just a thin wrapper over the shared OpenAICompatibleProvider - see
openai_compatible_provider.py for the actual request/response handling.
"""
from __future__ import annotations

from alex.ai.openai_compatible_provider import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(self, api_key: str, base_url: str, model: str):
        # OpenRouter uses these two optional headers for its public
        # leaderboard/analytics - harmless to include, fine to omit.
        super().__init__(
            name="openrouter",
            api_key=api_key,
            base_url=base_url,
            model=model,
            extra_headers={
                "HTTP-Referer": "https://github.com/Nrpp/Proyect-ALEX",
                "X-Title": "ALEX Personal Assistant",
            },
        )
