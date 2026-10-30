"""Picks the active AIProvider from config. The only place that knows every provider exists."""
from __future__ import annotations

from alex.ai.base import AIProvider
from alex.config import Settings
from alex.core.errors import ConfigError

_KNOWN_PROVIDERS = ("nvidia", "anthropic", "openrouter", "anyapi")


def build_ai_provider(settings: Settings) -> AIProvider:
    primary = _build_single(settings, settings.ai_provider)
    fallbacks = _parse_fallbacks(settings.ai_fallbacks)
    if not fallbacks:
        return primary

    from alex.ai.fallback_provider import FallbackProvider

    chain = [(f"{settings.ai_provider}:{_default_model(settings, settings.ai_provider)}", primary)]
    for provider_name, model in fallbacks:
        chain.append((f"{provider_name}:{model or _default_model(settings, provider_name)}",
                      _build_single(settings, provider_name, model)))
    return FallbackProvider(
        chain,
        attempt_timeout_seconds=settings.ai_fallback_attempt_timeout_seconds,
        cooldown_seconds=settings.ai_fallback_cooldown_seconds,
    )


def _parse_fallbacks(raw: str) -> list[tuple[str, str | None]]:
    """
    "nvidia:openai/gpt-oss-20b, anyapi:google/gemma-4-26b-a4b-it:free, anthropic"
    -> [("nvidia", "openai/gpt-oss-20b"), ("anyapi", "google/gemma-4-26b-a4b-it:free"), ("anthropic", None)]

    Only the first ":" separates provider from model - model ids themselves
    can contain ":" (e.g. the ":free" suffix). A bare provider name uses that
    provider's configured model.
    """
    entries = []
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        provider_name, _, model = item.partition(":")
        entries.append((provider_name.strip(), model.strip() or None))
    return entries


def _default_model(settings: Settings, provider_name: str) -> str:
    return getattr(settings, f"{provider_name}_model", "")


def _build_single(settings: Settings, provider_name: str, model: str | None = None) -> AIProvider:
    if provider_name == "nvidia":
        from alex.ai.nvidia_provider import NvidiaProvider

        return NvidiaProvider(
            api_key=settings.nvidia_api_key,
            base_url=settings.nvidia_base_url,
            model=model or settings.nvidia_model,
        )
    if provider_name == "anthropic":
        from alex.ai.anthropic_provider import AnthropicProvider

        return AnthropicProvider(api_key=settings.anthropic_api_key, model=model or settings.anthropic_model)

    if provider_name == "openrouter":
        from alex.ai.openrouter_provider import OpenRouterProvider

        return OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            model=model or settings.openrouter_model,
        )

    if provider_name == "anyapi":
        from alex.ai.anyapi_provider import AnyAPIProvider

        return AnyAPIProvider(
            api_key=settings.anyapi_api_key,
            base_url=settings.anyapi_base_url,
            model=model or settings.anyapi_model,
        )

    raise ConfigError(
        f"Unknown AI provider '{provider_name}'. Expected one of: {', '.join(_KNOWN_PROVIDERS)}."
    )
