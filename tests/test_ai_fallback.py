from __future__ import annotations

import asyncio

import pytest

from alex.ai.anyapi_provider import AnyAPIProvider
from alex.ai.base import AIProvider, AIResponse, ChatMessage
from alex.ai.fallback_provider import FallbackProvider
from alex.ai.nvidia_provider import NvidiaProvider
from alex.ai.router import _parse_fallbacks, build_ai_provider
from alex.config import Settings
from alex.core.errors import AIProviderError


class FakeProvider(AIProvider):
    def __init__(self, name: str, *, fail: bool = False, hang: bool = False, healthy: bool = True):
        self.name = name
        self.fail = fail
        self.hang = hang
        self.healthy = healthy
        self.calls = 0
        self.health_calls = 0

    async def complete(self, messages, *, system, tools=None, max_tokens=1024, temperature=0.4):
        self.calls += 1
        if self.hang:
            await asyncio.sleep(10)
        if self.fail:
            raise AIProviderError(f"{self.name} is down")
        return AIResponse(content=f"answer from {self.name}")

    async def health_check(self) -> bool:
        self.health_calls += 1
        return self.healthy


MSGS = [ChatMessage(role="user", content="hola")]


def _chain(*providers: FakeProvider, cooldown: float = 300) -> FallbackProvider:
    return FallbackProvider(
        [(p.name, p) for p in providers], attempt_timeout_seconds=0.2, cooldown_seconds=cooldown,
    )


async def test_uses_primary_when_it_works():
    a, b = FakeProvider("a"), FakeProvider("b")
    resp = await _chain(a, b).complete(MSGS, system="s")
    assert resp.content == "answer from a"
    assert b.calls == 0


async def test_falls_back_on_error_and_reports_active_provider():
    a, b = FakeProvider("a", fail=True), FakeProvider("b")
    chain = _chain(a, b)
    resp = await chain.complete(MSGS, system="s")
    assert resp.content == "answer from b"
    assert chain.name == "b"


async def test_falls_back_on_timeout():
    a, b = FakeProvider("a", hang=True), FakeProvider("b")
    resp = await _chain(a, b).complete(MSGS, system="s")
    assert resp.content == "answer from b"


async def test_failed_provider_is_skipped_during_cooldown():
    a, b = FakeProvider("a", fail=True), FakeProvider("b")
    chain = _chain(a, b)
    await chain.complete(MSGS, system="s")
    await chain.complete(MSGS, system="s")
    assert a.calls == 1
    assert b.calls == 2


async def test_failed_provider_is_retried_after_cooldown():
    a, b = FakeProvider("a", fail=True), FakeProvider("b")
    chain = _chain(a, b, cooldown=0)
    await chain.complete(MSGS, system="s")
    a.fail = False
    resp = await chain.complete(MSGS, system="s")
    assert resp.content == "answer from a"
    assert chain.name == "a"


async def test_cooling_providers_are_still_tried_as_last_resort():
    a, b = FakeProvider("a", fail=True), FakeProvider("b", fail=True)
    chain = _chain(a, b)
    with pytest.raises(AIProviderError):
        await chain.complete(MSGS, system="s")
    a.fail = False
    resp = await chain.complete(MSGS, system="s")
    assert resp.content == "answer from a"


async def test_all_failing_raises_with_every_reason():
    a, b = FakeProvider("a", fail=True), FakeProvider("b", fail=True)
    with pytest.raises(AIProviderError) as exc:
        await _chain(a, b).complete(MSGS, system="s")
    assert "a is down" in exc.value.message
    assert "b is down" in exc.value.message


async def test_health_check_stops_at_first_healthy_provider():
    a, b, c = FakeProvider("a", healthy=False), FakeProvider("b"), FakeProvider("c")
    assert await _chain(a, b, c).health_check() is True
    assert c.health_calls == 0


async def test_health_check_false_when_none_healthy():
    a, b = FakeProvider("a", healthy=False), FakeProvider("b", healthy=False)
    assert await _chain(a, b).health_check() is False


def test_parse_fallbacks_keeps_colons_inside_model_ids():
    assert _parse_fallbacks(" nvidia:openai/gpt-oss-20b, anyapi:google/gemma:free ,anthropic,") == [
        ("nvidia", "openai/gpt-oss-20b"),
        ("anyapi", "google/gemma:free"),
        ("anthropic", None),
    ]


def test_router_without_fallbacks_returns_single_provider():
    provider = build_ai_provider(Settings(ai_provider="nvidia", ai_fallbacks=""))
    assert isinstance(provider, NvidiaProvider)


def test_router_builds_fallback_chain():
    settings = Settings(
        ai_provider="nvidia",
        nvidia_model="primary-model",
        anyapi_model="anyapi-default",
        ai_fallbacks="nvidia:second-model,anyapi",
    )
    provider = build_ai_provider(settings)
    assert isinstance(provider, FallbackProvider)
    labels = [label for label, _ in provider._providers]
    assert labels == ["nvidia:primary-model", "nvidia:second-model", "anyapi:anyapi-default"]
    assert provider._providers[1][1]._model == "second-model"
    assert isinstance(provider._providers[2][1], AnyAPIProvider)
