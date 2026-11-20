"""Provider-independent LLM abstraction.

`OpenAIProvider` uses the Chat Completions API with strict JSON-schema structured outputs.
`RuleBasedProvider` is an explicitly-labelled deterministic substitute used when no API key is
configured (local dev, CI). It never pretends to be an LLM: executions record provider="rule_based".
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import get_settings


@dataclass
class Completion:
    output: dict[str, Any]
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMProvider(Protocol):
    name: str
    model: str

    async def structured(
        self, *, system: str, user: str, schema_name: str, schema: dict[str, Any], fallback: Any
    ) -> Completion: ...


class OpenAIProvider:
    name = "openai"

    def __init__(self, api_key: str, model: str):
        from openai import AsyncOpenAI

        self.client = AsyncOpenAI(api_key=api_key)
        self.model = model

    async def structured(self, *, system, user, schema_name, schema, fallback) -> Completion:
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema_name, "schema": schema, "strict": True},
            },
            temperature=0,
        )
        content = resp.choices[0].message.content or "{}"
        usage = resp.usage
        return Completion(
            output=json.loads(content),
            provider=self.name,
            model=self.model,
            prompt_tokens=getattr(usage, "prompt_tokens", 0) or 0,
            completion_tokens=getattr(usage, "completion_tokens", 0) or 0,
        )


class RuleBasedProvider:
    """Deterministic fallback: each agent supplies a `fallback(user_input)` function."""

    name = "rule_based"
    model = "deterministic-v1"

    async def structured(self, *, system, user, schema_name, schema, fallback) -> Completion:
        return Completion(output=fallback(), provider=self.name, model=self.model)


_override: LLMProvider | None = None


def set_provider(p: LLMProvider | None) -> None:
    global _override
    _override = p


def get_provider() -> LLMProvider:
    if _override is not None:
        return _override
    s = get_settings()
    if s.openai_api_key:
        return OpenAIProvider(s.openai_api_key, s.openai_model)
    return RuleBasedProvider()
