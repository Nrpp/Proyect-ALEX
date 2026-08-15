"""
Shared implementation for any OpenAI-compatible chat-completions API. The
`openai` SDK is used purely as an HTTP client pointed at a different
base_url - none of these are actually OpenAI's own service.

Both NvidiaProvider and OpenRouterProvider are thin subclasses of this that
just supply their own name/base_url/api_key/model - adding another
OpenAI-compatible provider later (Groq, Together, a local vLLM/Ollama
server exposing an OpenAI-style endpoint, ...) is a ~10-line file, not a
rewrite.
"""
from __future__ import annotations

import json
import logging

from openai import APIError, AsyncOpenAI

from alex.ai.base import AIProvider, AIResponse, ChatMessage, ToolCall, ToolSpec
from alex.core.errors import AIProviderError

log = logging.getLogger(__name__)


class OpenAICompatibleProvider(AIProvider):
    def __init__(
        self, *, name: str, api_key: str, base_url: str, model: str,
        extra_headers: dict[str, str] | None = None,
    ):
        self.name = name
        if not api_key:
            log.warning("No API key configured for provider '%s' - calls will fail", name)
        self._client = AsyncOpenAI(
            api_key=api_key or "missing", base_url=base_url, default_headers=extra_headers or None,
        )
        self._model = model

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        system: str,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.4,
    ) -> AIResponse:
        payload_messages = [{"role": "system", "content": system}]
        for m in messages:
            entry: dict = {"role": m.role, "content": m.content}
            if m.role == "assistant" and m.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in m.tool_calls
                ]
            if m.role == "tool":
                entry["tool_call_id"] = m.tool_call_id
                entry["name"] = m.name
            payload_messages.append(entry)

        kwargs: dict = dict(
            model=self._model,
            messages=payload_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if tools:
            kwargs["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.parameters,
                    },
                }
                for t in tools
            ]
            kwargs["tool_choice"] = "auto"

        try:
            resp = await self._client.chat.completions.create(**kwargs)
        except APIError as e:
            raise AIProviderError(f"{self.name} request failed: {e}") from e

        choice = resp.choices[0]
        msg = choice.message
        tool_calls: list[ToolCall] = []
        for tc in getattr(msg, "tool_calls", None) or []:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, arguments=args))

        usage = None
        if resp.usage:
            usage = {
                "input_tokens": resp.usage.prompt_tokens,
                "output_tokens": resp.usage.completion_tokens,
            }

        return AIResponse(
            content=msg.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
            raw_usage=usage,
        )

    async def health_check(self) -> bool:
        try:
            await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
            )
            return True
        except Exception:
            log.exception("%s health check failed", self.name)
            return False
