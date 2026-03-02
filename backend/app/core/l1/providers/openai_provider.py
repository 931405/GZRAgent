"""
OpenAI-Compatible LLM Provider.

Supports: OpenAI, DeepSeek, and any OpenAI API-compatible endpoint.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from app.core.l1.llm_provider import (
    BaseLLMProvider,
    ChatMessage,
    LLMProviderFactory,
    LLMResponse,
    LLMStreamChunk,
)

logger = logging.getLogger(__name__)


class OpenAIProvider(BaseLLMProvider):
    """Provider for OpenAI and OpenAI-compatible APIs (DeepSeek, etc.)."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url or None,
            timeout=self.timeout,
            max_retries=self.max_retries,
        )

    async def complete(
        self,
        messages: list[ChatMessage],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        resolved_model = self._resolve_model(model)
        response = await self._client.chat.completions.create(
            model=resolved_model,
            messages=self._messages_to_dicts(messages),  # type: ignore
            temperature=temperature,
            max_tokens=max_tokens,
            **kwargs,
        )
        choice = response.choices[0]
        usage = response.usage

        return LLMResponse(
            content=choice.message.content or "",
            model=response.model,
            prompt_tokens=usage.prompt_tokens if usage else 0,
            completion_tokens=usage.completion_tokens if usage else 0,
            total_tokens=usage.total_tokens if usage else 0,
            finish_reason=choice.finish_reason or "",
            raw=response.model_dump(),
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[LLMStreamChunk]:
        resolved_model = self._resolve_model(model)
        stream = await self._client.chat.completions.create(
            model=resolved_model,
            messages=self._messages_to_dicts(messages),  # type: ignore
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            **kwargs,
        )
        async for chunk in stream:
            if chunk.choices:
                delta = chunk.choices[0].delta
                yield LLMStreamChunk(
                    content=delta.content or "",
                    is_final=chunk.choices[0].finish_reason is not None,
                    model=chunk.model or resolved_model,
                )

    async def structured_output(
        self,
        messages: list[ChatMessage],
        response_schema: dict[str, Any],
        model: str = "",
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Use response_format for JSON mode
        resolved_model = self._resolve_model(model)

        # Add schema instruction to system message
        schema_instruction = (
            f"You must respond with valid JSON that conforms to this schema:\n"
            f"```json\n{json.dumps(response_schema, indent=2)}\n```"
        )
        augmented_messages = list(messages)
        if augmented_messages and augmented_messages[0].role == "system":
            augmented_messages[0] = ChatMessage(
                role="system",
                content=augmented_messages[0].content + "\n\n" + schema_instruction,
            )
        else:
            augmented_messages.insert(0, ChatMessage(
                role="system", content=schema_instruction
            ))

        response = await self._client.chat.completions.create(
            model=resolved_model,
            messages=self._messages_to_dicts(augmented_messages),  # type: ignore
            temperature=temperature,
            response_format={"type": "json_object"},
            **kwargs,
        )
        content = response.choices[0].message.content or "{}"
        return json.loads(content)


# Register providers
LLMProviderFactory.register("openai", OpenAIProvider)
LLMProviderFactory.register("deepseek", OpenAIProvider)  # DeepSeek uses OpenAI-compatible API
