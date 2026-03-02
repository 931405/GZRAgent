"""
PD-MAWS Global Configuration

Multi-LLM Provider support with per-agent assignment.
Uses pydantic-settings for environment variable loading.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProviderType(str, Enum):
    """Supported LLM provider types."""
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    CUSTOM = "custom"


class LLMProviderConfig(BaseSettings):
    """Configuration for a single LLM provider."""
    provider_type: LLMProviderType
    api_key: str = ""
    base_url: str = ""
    default_model: str = ""
    timeout: int = 120
    max_retries: int = 3


class Settings(BaseSettings):
    """Application-wide settings loaded from environment variables."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- Application ----
    app_name: str = "PD-MAWS"
    app_env: str = "development"
    app_debug: bool = True
    app_host: str = "0.0.0.0"
    app_port: int = 8000

    # ---- PostgreSQL ----
    database_url: str = "postgresql+asyncpg://pdmaws:pdmaws_dev_2024@localhost:5432/pdmaws"

    # ---- Redis ----
    redis_url: str = "redis://localhost:6379/0"

    # ---- Qdrant ----
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333

    # ---- JWT Security ----
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 60

    # ---- HMAC Message Signing ----
    hmac_secret_key: str = "change-me-in-production"

    # ---- LLM Provider Configs ----
    # OpenAI (also works for DeepSeek with base_url override)
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_default_model: str = "gpt-4o"

    # DeepSeek
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    deepseek_default_model: str = "deepseek-chat"

    # Google Gemini
    gemini_api_key: str = ""
    gemini_default_model: str = "gemini-2.5-pro"

    # Ollama
    ollama_base_url: str = "http://localhost:11434"
    ollama_default_model: str = "llama3"

    # Custom
    custom_llm_base_url: str = ""
    custom_llm_api_key: str = ""
    custom_llm_default_model: str = "custom-model"

    # ---- Per-Agent LLM Assignment ----
    agent_pi_provider: LLMProviderType = LLMProviderType.OPENAI
    agent_pi_model: str = ""
    agent_writer_provider: LLMProviderType = LLMProviderType.DEEPSEEK
    agent_writer_model: str = ""
    agent_researcher_provider: LLMProviderType = LLMProviderType.OPENAI
    agent_researcher_model: str = ""
    agent_red_team_provider: LLMProviderType = LLMProviderType.OPENAI
    agent_red_team_model: str = ""
    agent_diagram_provider: LLMProviderType = LLMProviderType.OPENAI
    agent_diagram_model: str = ""
    agent_format_provider: LLMProviderType = LLMProviderType.DEEPSEEK
    agent_format_model: str = ""
    agent_data_analyst_provider: LLMProviderType = LLMProviderType.OPENAI
    agent_data_analyst_model: str = ""

    # ---- Token Budget ----
    global_token_hard_limit: int = 2_000_000
    agent_token_soft_limit: int = 200_000

    # ---- Observability ----
    otel_exporter_otlp_endpoint: str = "http://localhost:4317"

    def get_provider_config(self, provider_type: LLMProviderType) -> LLMProviderConfig:
        """Get the configuration for a specific LLM provider type."""
        configs = {
            LLMProviderType.OPENAI: LLMProviderConfig(
                provider_type=LLMProviderType.OPENAI,
                api_key=self.openai_api_key,
                base_url=self.openai_base_url,
                default_model=self.openai_default_model,
            ),
            LLMProviderType.DEEPSEEK: LLMProviderConfig(
                provider_type=LLMProviderType.DEEPSEEK,
                api_key=self.deepseek_api_key,
                base_url=self.deepseek_base_url,
                default_model=self.deepseek_default_model,
            ),
            LLMProviderType.GEMINI: LLMProviderConfig(
                provider_type=LLMProviderType.GEMINI,
                api_key=self.gemini_api_key,
                default_model=self.gemini_default_model,
            ),
            LLMProviderType.OLLAMA: LLMProviderConfig(
                provider_type=LLMProviderType.OLLAMA,
                base_url=self.ollama_base_url,
                default_model=self.ollama_default_model,
            ),
            LLMProviderType.CUSTOM: LLMProviderConfig(
                provider_type=LLMProviderType.CUSTOM,
                api_key=self.custom_llm_api_key,
                base_url=self.custom_llm_base_url,
                default_model=self.custom_llm_default_model,
            ),
        }
        return configs[provider_type]

    def get_agent_llm_config(
        self, agent_name: str
    ) -> tuple[LLMProviderType, str]:
        """Get the LLM provider type and model for a specific agent.

        Returns:
            (provider_type, model_name) where model_name may be empty (use default).
        """
        attr_provider = f"agent_{agent_name}_provider"
        attr_model = f"agent_{agent_name}_model"
        provider = getattr(self, attr_provider, LLMProviderType.OPENAI)
        model = getattr(self, attr_model, "")
        return provider, model


# Singleton
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create the global settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
