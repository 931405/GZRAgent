"""
PD-MAWS FastAPI Application Entry Point.

Initializes all subsystems and exposes the unified API.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any, Optional, AsyncGenerator

import redis.asyncio as aioredis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.core.anp.registry import SessionRegistry
from app.core.anp.blackboard import BlackboardManager
from app.core.anp.circuit_breaker import TokenCircuitBreaker
from app.core.anp.deadlock import DeadlockDetector
from app.core.a2a.bus import MessageBus
from app.core.a2a.validator import A2AValidator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global singletons (initialized on startup)
# ---------------------------------------------------------------------------

_redis_client: Optional[aioredis.Redis] = None
_session_registry: Optional[SessionRegistry] = None
_blackboard: Optional[BlackboardManager] = None
_circuit_breaker: Optional[TokenCircuitBreaker] = None
_deadlock_detector: Optional[DeadlockDetector] = None
_message_bus: Optional[MessageBus] = None
_validator: Optional[A2AValidator] = None


def get_registry() -> SessionRegistry:
    assert _session_registry is not None, "SessionRegistry not initialized"
    return _session_registry


def get_blackboard() -> BlackboardManager:
    assert _blackboard is not None, "BlackboardManager not initialized"
    return _blackboard


def get_circuit_breaker() -> TokenCircuitBreaker:
    assert _circuit_breaker is not None, "TokenCircuitBreaker not initialized"
    return _circuit_breaker


def get_message_bus() -> MessageBus:
    assert _message_bus is not None, "MessageBus not initialized"
    return _message_bus


def get_validator() -> A2AValidator:
    assert _validator is not None, "A2AValidator not initialized"
    return _validator


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: initialize and clean up subsystems."""
    global _redis_client, _session_registry, _blackboard
    global _circuit_breaker, _deadlock_detector, _message_bus, _validator

    settings = get_settings()

    # Initialize Redis
    _redis_client = aioredis.from_url(
        settings.redis_url,
        decode_responses=False,
    )
    logger.info("Redis connected: %s", settings.redis_url)

    # Initialize core subsystems
    _session_registry = SessionRegistry(_redis_client)
    _blackboard = BlackboardManager(_redis_client)
    _circuit_breaker = TokenCircuitBreaker(
        _redis_client,
        global_hard_limit=settings.global_token_hard_limit,
        agent_soft_limit=settings.agent_token_soft_limit,
    )
    _deadlock_detector = DeadlockDetector(_session_registry)
    _message_bus = MessageBus(_redis_client)
    _validator = A2AValidator(
        _redis_client,
        _session_registry,
        hmac_secret=settings.hmac_secret_key,
    )

    logger.info("PD-MAWS subsystems initialized")

    # Initialize database tables
    from app.db import init_db
    await init_db()
    # Register LLM providers (import triggers registration)
    from app.core.l1.providers import openai_provider, gemini_provider  # noqa: F401
    from app.core.l1.providers import ollama_provider, custom_provider   # noqa: F401

    yield

    # Cleanup
    if _message_bus:
        await _message_bus.close()
    if _redis_client:
        await _redis_client.close()
    logger.info("PD-MAWS shutdown complete")


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="PD-MAWS",
        description=(
            "Protocol-Driven Multi-Agent Academic Writing System. "
            "A production-grade, auditable, multi-agent system for "
            "collaborative academic paper writing."
        ),
        version="0.1.0",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Register routers
    from app.api.sessions import router as sessions_router
    from app.api.websocket import router as websocket_router

    app.include_router(sessions_router)
    app.include_router(websocket_router)

    return app


# Create app instance
app = create_app()


# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
