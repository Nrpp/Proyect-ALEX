"""Picks the active AIProvider from config. The only place that knows every provider exists."""
from __future__ import annotations

from alex.ai.base import AIProvider
from alex.config import Settings
from alex.core.errors import ConfigError

_KNOWN_PROVIDERS = ("nvidia", "anthropic", "openrouter")


def build_ai_provider(settings: Settings) -> AIProvider:
    if settings.ai_provider == "nvidia":
        from alex.ai.nvidia_provider import NvidiaProvider

        return NvidiaProvider(
            api_key=settings.nvidia_api_key,
            base_url=settings.nvidia_base_url,
            model=settings.nvidia_model,
        )
    if settings.ai_provider == "anthropic":
        from alex.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=settings.anthropic_api_key, model=settings.anthropic_model)

    if settings.ai_provider == "openrouter":
        from alex.ai.openrouter_provider import OpenRouterProvider

        return OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            model=settings.openrouter_model,
        )

    raise ConfigError(
        f"Unknown ALEX_AI_PROVIDER '{settings.ai_provider}'. Expected one of: {', '.join(_KNOWN_PROVIDERS)}."
    )
