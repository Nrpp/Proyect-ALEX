"""
Fallback chain over several AIProviders. Free-tier models get delisted,
rate-limited or renamed with no warning (seen in practice on both NVIDIA NIM
and AnyAPI), so instead of ALEX going silent until someone edits .env, each
turn tries the configured providers in order and answers with the first one
that works.

A provider that fails is put on cooldown for a while, so later turns go
straight to one that works instead of paying the failing call's latency
every time. If every provider is cooling down they are all tried anyway -
a cooldown is a preference, never a reason to give up.

Built by alex/ai/router.py only when ALEX_AI_FALLBACKS is set; with no
fallbacks configured ALEX uses the single primary provider exactly as before.
"""
from __future__ import annotations

import asyncio
import logging
import time

from alex.ai.base import AIProvider, AIResponse, ChatMessage, ToolSpec
from alex.core.errors import AIProviderError

log = logging.getLogger(__name__)


class FallbackProvider(AIProvider):
    def __init__(
        self,
        providers: list[tuple[str, AIProvider]],
        *,
        attempt_timeout_seconds: float,
        cooldown_seconds: float,
    ):
        if not providers:
            raise ValueError("FallbackProvider needs at least one provider")
        # (label, provider) pairs - label is "provider:model", since the same
        # provider can appear several times with different models.
        self._providers = providers
        self._attempt_timeout = attempt_timeout_seconds
        self._cooldown = cooldown_seconds
        self._down_until: dict[str, float] = {}
        # Reported in /health and logs: whichever provider answered last.
        self.name = providers[0][0]

    def _ordered(self) -> list[tuple[str, AIProvider]]:
        now = time.monotonic()
        ready = [p for p in self._providers if self._down_until.get(p[0], 0) <= now]
        cooling = [p for p in self._providers if self._down_until.get(p[0], 0) > now]
        return ready + cooling

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        system: str,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.4,
    ) -> AIResponse:
        errors: list[str] = []
        for label, provider in self._ordered():
            try:
                resp = await asyncio.wait_for(
                    provider.complete(
                        messages, system=system, tools=tools,
                        max_tokens=max_tokens, temperature=temperature,
                    ),
                    timeout=self._attempt_timeout,
                )
            except (AIProviderError, asyncio.TimeoutError) as e:
                reason = str(e) or f"timed out after {self._attempt_timeout}s"
                log.warning("AI provider %s failed, trying next: %s", label, reason)
                errors.append(f"{label}: {reason}")
                self._down_until[label] = time.monotonic() + self._cooldown
                continue
            self._down_until.pop(label, None)
            if label != self.name:
                log.info("AI provider switched to %s", label)
                self.name = label
            return resp
        raise AIProviderError("All AI providers failed - " + " | ".join(errors))

    async def health_check(self) -> bool:
        # Stops at the first healthy provider so a routine /health poll costs
        # one request, not one per provider.
        for _label, provider in self._ordered():
            if await provider.health_check():
                return True
        return False
