"""
SQLModel for persisted LLM configuration settings.

API keys are stored encrypted using Fernet (AES).
A single row (singleton pattern via key='global') holds all config.
"""
from __future__ import annotations

from typing import Optional
from sqlmodel import SQLModel, Field
from datetime import datetime, timezone


class LLMSettingsRow(SQLModel, table=True):
    """Persisted LLM provider and agent configuration.

    Uses a key-value approach: one row per config entry.
    Keys follow the pattern: provider.<name>.<field> or agent.<name>.<field>
    Sensitive values (API keys) are stored encrypted.
    """
    __tablename__ = "llm_settings"

    id: Optional[int] = Field(default=None, primary_key=True)
    config_key: str = Field(index=True, unique=True, max_length=128)
    config_value: str = Field(default="", max_length=2048)
    is_encrypted: bool = Field(default=False)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
