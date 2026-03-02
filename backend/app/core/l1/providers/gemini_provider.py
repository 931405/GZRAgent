"""
Google Gemini LLM Provider.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

from app.core.l1.llm_provider import (
    BaseLLMProvider,
    ChatMessage,
    LLMProviderFactory,
    LLMResponse,
    LLMStreamChunk,
)

logger = logging.getLogger(__name__)


class GeminiProvider(BaseLLMProvider):
    """Provider for Google Gemini API."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client = None  # Lazy init

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai
            self._client = genai.Client(api_key=self.api_key)
        return self._client

    def _convert_messages(
        self, messages: list[ChatMessage]
    ) -> tuple[str, list[dict]]:
        """Convert ChatMessages to Gemini format.

        Returns (system_instruction, contents).
        """
        system = ""
        contents = []
        for msg in messages:
            if msg.role == "system":
                system = msg.content
            elif msg.role == "user":
                contents.append({"role": "user", "parts": [{"text": msg.content}]})
            elif msg.role == "assistant":
                contents.append({"role": "model", "parts": [{"text": msg.content}]})
        return system, contents

    async def complete(
        self,
        messages: list[ChatMessage],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        client = self._get_client()
        resolved_model = self._resolve_model(model)
        system, contents = self._convert_messages(messages)

        from google.genai import types
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system if system else None,
        )

        response = await client.aio.models.generate_content(
            model=resolved_model,
            contents=contents,
            config=config,
        )

        usage_meta = getattr(response, "usage_metadata", None)
        return LLMResponse(
            content=response.text or "",
            model=resolved_model,
            prompt_tokens=getattr(usage_meta, "prompt_token_count", 0) or 0,
            completion_tokens=getattr(usage_meta, "candidates_token_count", 0) or 0,
            total_tokens=getattr(usage_meta, "total_token_count", 0) or 0,
            finish_reason="stop",
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[LLMStreamChunk]:
        client = self._get_client()
        resolved_model = self._resolve_model(model)
        system, contents = self._convert_messages(messages)

        from google.genai import types
        config = types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
            system_instruction=system if system else None,
        )

        async for chunk in await client.aio.models.generate_content_stream(
            model=resolved_model,
            contents=contents,
            config=config,
        ):
            yield LLMStreamChunk(
                content=chunk.text or "",
                is_final=False,
                model=resolved_model,
            )
        yield LLMStreamChunk(content="", is_final=True, model=resolved_model)

    async def structured_output(
        self,
        messages: list[ChatMessage],
        response_schema: dict[str, Any],
        model: str = "",
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> dict[str, Any]:
        schema_text = (
            f"Respond ONLY with valid JSON conforming to:\n"
            f"```json\n{json.dumps(response_schema, indent=2)}\n```"
        )
        augmented = list(messages)
        augmented.append(ChatMessage(role="user", content=schema_text))

        response = await self.complete(
            augmented, model=model, temperature=temperature
        )
        # Extract JSON from response
        text = response.content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        return json.loads(text)


LLMProviderFactory.register("gemini", GeminiProvider)
