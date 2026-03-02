"""
Ollama LLM Provider (Local).

Uses OpenAI-compatible API exposed by Ollama.
"""
from __future__ import annotations

from typing import Any

from app.core.l1.providers.openai_provider import OpenAIProvider
from app.core.l1.llm_provider import LLMProviderFactory


class OllamaProvider(OpenAIProvider):
    """Provider for local Ollama models via OpenAI-compatible API."""

    def __init__(self, **kwargs: Any) -> None:
        # Default to Ollama's local endpoint
        if not kwargs.get("base_url"):
            kwargs["base_url"] = "http://localhost:11434/v1"
        if not kwargs.get("api_key"):
            kwargs["api_key"] = "ollama"  # Ollama doesn't require a key
        super().__init__(**kwargs)


LLMProviderFactory.register("ollama", OllamaProvider)
