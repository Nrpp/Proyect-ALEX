"""
Anthropic Claude provider.

Used either as ALEX's primary provider (`ALEX_AI_PROVIDER=anthropic`) or as
a manual fallback. Kept behind the same `AIProvider` interface as the NVIDIA
provider, so switching is a one-line config change.
"""
from __future__ import annotations

import logging

import anthropic

from alex.ai.base import AIProvider, AIResponse, ChatMessage, ToolCall, ToolSpec
from alex.core.errors import AIProviderError

log = logging.getLogger(__name__)


class AnthropicProvider(AIProvider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str):
        if not api_key:
            log.warning("ALEX_ANTHROPIC_API_KEY is empty - Anthropic provider calls will fail")
        self._client = anthropic.AsyncAnthropic(api_key=api_key or "missing")
        self._model = model

    def _to_anthropic_messages(self, messages: list[ChatMessage]) -> list[dict]:
        """
        Anthropic requires strictly alternating user/assistant turns and has
        no separate "tool" role - tool results are user-turn content blocks.
        We fold consecutive tool-result ChatMessages into a single user turn.
        """
        out: list[dict] = []
        for m in messages:
            if m.role == "assistant":
                content: list[dict] = []
                if m.content:
                    content.append({"type": "text", "text": m.content})
                for tc in m.tool_calls or []:
                    content.append(
                        {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                    )
                out.append({"role": "assistant", "content": content})
            elif m.role == "tool":
                block = {
                    "type": "tool_result",
                    "tool_use_id": m.tool_call_id,
                    "content": m.content,
                }
                if out and out[-1]["role"] == "user" and _is_tool_result_turn(out[-1]):
                    out[-1]["content"].append(block)
                else:
                    out.append({"role": "user", "content": [block]})
            else:  # user
                out.append({"role": "user", "content": m.content})
        return out

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        system: str,
        tools: list[ToolSpec] | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.4,
    ) -> AIResponse:
        kwargs: dict = dict(
            model=self._model,
            system=system,
            messages=self._to_anthropic_messages(messages),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description, "input_schema": t.parameters}
                for t in tools
            ]

        try:
            resp = await self._client.messages.create(**kwargs)
        except anthropic.APIError as e:
            raise AIProviderError(f"Anthropic request failed: {e}") from e

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, arguments=block.input))

        usage = None
        if resp.usage:
            usage = {
                "input_tokens": resp.usage.input_tokens,
                "output_tokens": resp.usage.output_tokens,
            }

        return AIResponse(
            content="\n".join(text_parts) if text_parts else None,
            tool_calls=tool_calls,
            finish_reason=resp.stop_reason or "stop",
            raw_usage=usage,
        )

    async def health_check(self) -> bool:
        try:
            await self._client.messages.create(
                model=self._model,
                max_tokens=1,
                messages=[{"role": "user", "content": "ping"}],
            )
            return True
        except Exception:
            log.exception("Anthropic health check failed")
            return False


def _is_tool_result_turn(turn: dict) -> bool:
    return isinstance(turn.get("content"), list) and all(
        isinstance(b, dict) and b.get("type") == "tool_result" for b in turn["content"]
    )
