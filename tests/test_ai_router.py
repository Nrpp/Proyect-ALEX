from __future__ import annotations

import pytest

from alex.ai.anyapi_provider import AnyAPIProvider
from alex.ai.nvidia_provider import NvidiaProvider
from alex.ai.openrouter_provider import OpenRouterProvider
from alex.ai.router import build_ai_provider
from alex.config import Settings
from alex.core.errors import ConfigError


def test_router_builds_nvidia_provider_by_default():
    settings = Settings(ai_provider="nvidia", nvidia_model="some-model")
    provider = build_ai_provider(settings)
    assert isinstance(provider, NvidiaProvider)
    assert provider.name == "nvidia"


def test_router_builds_openrouter_provider():
    settings = Settings(
        ai_provider="openrouter",
        openrouter_api_key="test-key",
        openrouter_model="meta-llama/llama-3.1-8b-instruct:free",
    )
    provider = build_ai_provider(settings)
    assert isinstance(provider, OpenRouterProvider)
    assert provider.name == "openrouter"
    assert "openrouter.ai" in str(provider._client.base_url)


def test_router_builds_anyapi_provider():
    settings = Settings(
        ai_provider="anyapi",
        anyapi_api_key="test-key",
        anyapi_model="meta-llama/llama-3.3-70b-instruct:free",
    )
    provider = build_ai_provider(settings)
    assert isinstance(provider, AnyAPIProvider)
    assert provider.name == "anyapi"
    assert "anyapi.ai" in str(provider._client.base_url)


def test_router_rejects_unknown_provider():
    settings = Settings(ai_provider="not-a-real-provider")
    with pytest.raises(ConfigError):
        build_ai_provider(settings)
