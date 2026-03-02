"""
Multi-LLM Provider Abstraction Layer.

Provides a unified interface for interacting with different LLM providers.
Each agent can be configured to use a different provider/model.

Supported providers:
  - OpenAI (also compatible with DeepSeek via base_url)
  - Google Gemini
  - Ollama (local)
  - Custom HTTP endpoint

Ref: tech_stack.md Section 3 (LangChain for tool integration)
"""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Unified response models
# ---------------------------------------------------------------------------

class LLMResponse(BaseModel):
    """Unified LLM response across all providers."""
    content: str = ""
    model: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    finish_reason: str = ""
    raw: dict[str, Any] = {}


class LLMStreamChunk(BaseModel):
    """A single chunk from streaming response."""
    content: str = ""
    is_final: bool = False
    model: str = ""


class ChatMessage(BaseModel):
    """A chat message for multi-turn conversations."""
    role: str  # system, user, assistant, tool
    content: str
    name: Optional[str] = None
    tool_calls: Optional[list[dict]] = None
    tool_call_id: Optional[str] = None


# ---------------------------------------------------------------------------
# Abstract Base Provider
# ---------------------------------------------------------------------------

class BaseLLMProvider(ABC):
    """Abstract base class for all LLM providers.

    Subclasses must implement complete(), stream(), and structured_output().
    """

    def __init__(
        self,
        api_key: str = "",
        base_url: str = "",
        default_model: str = "",
        timeout: int = 120,
        max_retries: int = 3,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.default_model = default_model
        self.timeout = timeout
        self.max_retries = max_retries

    @abstractmethod
    async def complete(
        self,
        messages: list[ChatMessage],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a complete response."""
        ...

    @abstractmethod
    async def stream(
        self,
        messages: list[ChatMessage],
        model: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Stream response chunks."""
        ...

    @abstractmethod
    async def structured_output(
        self,
        messages: list[ChatMessage],
        response_schema: dict[str, Any],
        model: str = "",
        temperature: float = 0.3,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Generate structured (JSON) output conforming to a schema."""
        ...

    def _resolve_model(self, model: str) -> str:
        """Resolve model name: use provided or fall back to default."""
        return model or self.default_model

    def _messages_to_dicts(
        self, messages: list[ChatMessage]
    ) -> list[dict[str, Any]]:
        """Convert ChatMessage list to list of dicts for API calls."""
        result = []
        for msg in messages:
            d: dict[str, Any] = {"role": msg.role, "content": msg.content}
            if msg.name:
                d["name"] = msg.name
            if msg.tool_calls:
                d["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                d["tool_call_id"] = msg.tool_call_id
            result.append(d)
        return result


# ---------------------------------------------------------------------------
# Provider Factory
# ---------------------------------------------------------------------------

class LLMProviderFactory:
    """Factory to create LLM provider instances based on configuration.

    Usage:
        from app.config import get_settings, LLMProviderType
        settings = get_settings()
        provider = LLMProviderFactory.create(
            LLMProviderType.OPENAI,
            settings.get_provider_config(LLMProviderType.OPENAI)
        )
    """

    _registry: dict[str, type[BaseLLMProvider]] = {}

    @classmethod
    def register(cls, provider_type: str, provider_class: type[BaseLLMProvider]) -> None:
        """Register a provider class."""
        cls._registry[provider_type] = provider_class

    @classmethod
    def create(cls, provider_type: str, **kwargs: Any) -> BaseLLMProvider:
        """Create a provider instance.

        Args:
            provider_type: Provider type string (openai, deepseek, gemini, etc.)
            **kwargs: Provider-specific configuration.

        Returns:
            An initialized BaseLLMProvider instance.
        """
        provider_class = cls._registry.get(provider_type)
        if provider_class is None:
            raise ValueError(
                f"Unknown LLM provider: {provider_type}. "
                f"Available: {list(cls._registry.keys())}"
            )
        return provider_class(**kwargs)

    @classmethod
    def available_providers(cls) -> list[str]:
        """List all registered provider types."""
        return list(cls._registry.keys())
