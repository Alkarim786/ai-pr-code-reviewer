"""LLM abstraction: a real Anthropic client and a scripted FakeLLM for tests/offline runs."""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class LLMResponse:
    content: list[dict[str, Any]]
    stop_reason: str = "end_turn"
    input_tokens: int = 0
    output_tokens: int = 0


class LLM(Protocol):
    async def complete(
        self, system: str, messages: list[dict], tools: list[dict]
    ) -> LLMResponse: ...


class AnthropicLLM:
    def __init__(
        self, model: str | None = None, max_tokens: int = 4096, api_key: str | None = None
    ):
        from anthropic import AsyncAnthropic

        self.model = model or os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")
        self.max_tokens = max_tokens
        self.client = AsyncAnthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))

    async def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=messages,
            tools=tools,
        )
        blocks = [b.model_dump(exclude_none=True) for b in resp.content]
        return LLMResponse(
            content=blocks,
            stop_reason=resp.stop_reason or "end_turn",
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
        )


@dataclass
class FakeLLM:
    """Replays scripted responses.

    `script(agent_name, turn, messages)` returns the content blocks for that turn
    (or None to end). The agent name is read from the `[agent:<name>]` tag the
    agent prompt carries.
    """

    script: Callable[[str, int, list[dict]], list[dict] | None]
    calls: list[tuple[str, int]] = field(default_factory=list)

    async def complete(self, system: str, messages: list[dict], tools: list[dict]) -> LLMResponse:
        agent = system.split("[agent:", 1)[1].split("]", 1)[0] if "[agent:" in system else "?"
        turn = sum(1 for m in messages if m["role"] == "assistant")
        self.calls.append((agent, turn))
        blocks = self.script(agent, turn, messages)
        if blocks is None:
            return LLMResponse(content=[{"type": "text", "text": "done"}])
        stop = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
        return LLMResponse(content=blocks, stop_reason=stop)


def tool_use(id_: str, name: str, **input_: Any) -> dict:
    return {"type": "tool_use", "id": id_, "name": name, "input": input_}
