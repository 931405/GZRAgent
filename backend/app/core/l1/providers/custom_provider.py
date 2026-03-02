"""
Custom HTTP LLM Provider.

Supports any LLM endpoint with configurable request/response format.
Designed for private deployments with non-standard APIs.
"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator

import httpx

from app.core.l1.llm_provider import (
    BaseLLMProvider,
    ChatMessage,
    LLMProviderFactory,
    LLMResponse,
    LLMStreamChunk,
)

logger = logging.getLogger(__name__)


class CustomProvider(BaseLLMProvider):
    """Provider for custom HTTP LLM endpoints.

    Configurable request/response format via kwargs:
      - request_template: dict template for the request body
      - response_content_path: dot-notation path to extract content
      - headers: additional HTTP headers

    Default format follows OpenAI-compatible structure.
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._headers = kwargs.get("headers", {})
        self._request_template = kwargs.get("request_template", None)
        self._response_content_path = kwargs.get(
            "response_content_path", "choices.0.message.content"
        )

        if self.api_key:
            self._headers.setdefault("Authorization", f"Bearer {self.api_key}")
        self._headers.setdefault("Content-Type", "application/json")

    def _build_request(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float,
        max_tokens: int,
        **kwargs: Any,
    ) -> dict:
        """Build request body. Uses template if provided, else OpenAI format."""
        if self._request_template:
            body = json.loads(json.dumps(self._request_template))
            body["messages"] = self._messages_to_dicts(messages)
            body["model"] = model
            return body

        return {
            "model": model,
            "messages": self._messages_to_dicts(messages),
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

    def _extract_content(self, data: dict) -> str:
        """Extract content from response using dot-notation path."""
        parts = self._response_content_path.split(".")
        current: Any = data
        for part in parts:
            if isinstance(current, dict):
                current = current.get(part, "")
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (IndexError, ValueError):
                    return ""
            else:
                return str(current)
        return str(current) if current else ""

    async def complete(
        self,
        messages: list[ChatMessage],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        resolved_model = self._resolve_model(model)
        body = self._build_request(
            messages, resolved_model, temperature, max_tokens, **kwargs
        )
        url = f"{self.base_url}/chat/completions"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=body, headers=self._headers)
            resp.raise_for_status()
            data = resp.json()

        return LLMResponse(
            content=self._extract_content(data),
            model=resolved_model,
            prompt_tokens=data.get("usage", {}).get("prompt_tokens", 0),
            completion_tokens=data.get("usage", {}).get("completion_tokens", 0),
            total_tokens=data.get("usage", {}).get("total_tokens", 0),
            finish_reason=data.get("choices", [{}])[0].get("finish_reason", ""),
            raw=data,
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
        body = self._build_request(
            messages, resolved_model, temperature, max_tokens, stream=True, **kwargs
        )
        url = f"{self.base_url}/chat/completions"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", url, json=body, headers=self._headers
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    if line.strip() == "[DONE]":
                        yield LLMStreamChunk(
                            content="", is_final=True, model=resolved_model
                        )
                        break
                    try:
                        chunk_data = json.loads(line)
                        content = (
                            chunk_data.get("choices", [{}])[0]
                            .get("delta", {})
                            .get("content", "")
                        )
                        yield LLMStreamChunk(
                            content=content or "",
                            is_final=False,
                            model=resolved_model,
                        )
                    except json.JSONDecodeError:
                        continue

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
            augmented, model=model, temperature=temperature, **kwargs
        )
        text = response.content.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:-1])
        return json.loads(text)


LLMProviderFactory.register("custom", CustomProvider)
