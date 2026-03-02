"""
Token Circuit Breaker — dual-layer token budget governance.

Layer 1 (Agent-side, soft): Sliding window budget per agent.
Layer 2 (ANP-side, hard): Global Redis atomic counter.

Ref: design.md Section 4.3
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import redis.asyncio as redis

logger = logging.getLogger(__name__)

# Redis keys
_GLOBAL_COUNTER_KEY = "pdmaws:token:global_total"
_GLOBAL_PROMPT_KEY = "pdmaws:token:global_prompt"
_GLOBAL_COMPLETION_KEY = "pdmaws:token:global_completion"
_HALT_FLAG_KEY = "pdmaws:token:halt_flag"
_AGENT_BUDGET_PREFIX = "pdmaws:token:agent:"


class CircuitBreakerTripped(Exception):
    """Raised when the global token hard limit is breached."""


class SoftBudgetExceeded(Exception):
    """Raised when an agent's local soft budget is exceeded."""


class TokenCircuitBreaker:
    """Dual-layer token budget governance.

    Prevents runaway token consumption:
    1. Local soft limit: per-agent sliding window (warns first, then degrades).
    2. Global hard limit: Redis atomic counter (immediate HALT broadcast).

    Recovery:
    - After HALT, only 'resume'/'terminate' control messages are allowed.
    - Human confirmation or budget reset required to resume.
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        global_hard_limit: int = 2_000_000,
        agent_soft_limit: int = 200_000,
    ) -> None:
        self._redis = redis_client
        self.global_hard_limit = global_hard_limit
        self.agent_soft_limit = agent_soft_limit

    # ------------------------------------------------------------------
    # Local soft limit (Agent side)
    # ------------------------------------------------------------------

    async def check_agent_budget(
        self, agent_id: str, requested_tokens: int = 0
    ) -> dict:
        """Check if an agent is within its soft budget.

        Returns: Dict with 'allowed', 'used', 'limit', 'utilization_pct'.
        Raises SoftBudgetExceeded if over limit.
        """
        key = f"{_AGENT_BUDGET_PREFIX}{agent_id}"
        used = await self._redis.get(key)
        used = int(used) if used else 0

        result = {
            "agent_id": agent_id,
            "used": used,
            "limit": self.agent_soft_limit,
            "utilization_pct": round((used / self.agent_soft_limit) * 100, 2)
            if self.agent_soft_limit > 0 else 0,
            "allowed": (used + requested_tokens) <= self.agent_soft_limit,
        }

        if not result["allowed"]:
            logger.warning(
                "Agent %s soft budget exceeded: %d/%d (requested +%d)",
                agent_id, used, self.agent_soft_limit, requested_tokens,
            )
            raise SoftBudgetExceeded(
                f"Agent {agent_id} exceeded soft limit: "
                f"{used}/{self.agent_soft_limit}"
            )

        return result

    async def record_agent_usage(
        self, agent_id: str, tokens: int
    ) -> int:
        """Record token usage for an agent. Returns new total."""
        key = f"{_AGENT_BUDGET_PREFIX}{agent_id}"
        new_total = await self._redis.incrby(key, tokens)
        return new_total

    # ------------------------------------------------------------------
    # Global hard limit (ANP side)
    # ------------------------------------------------------------------

    async def record_global_usage(
        self,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> dict:
        """Record global token usage atomically.

        Returns: Dict with 'total', 'prompt', 'completion', 'halted'.
        Raises CircuitBreakerTripped if hard limit breached.
        """
        # Atomic increment
        pipe = self._redis.pipeline()
        pipe.incrby(_GLOBAL_PROMPT_KEY, prompt_tokens)
        pipe.incrby(_GLOBAL_COMPLETION_KEY, completion_tokens)
        pipe.incrby(_GLOBAL_COUNTER_KEY, prompt_tokens + completion_tokens)
        results = await pipe.execute()

        new_prompt = results[0]
        new_completion = results[1]
        new_total = results[2]

        result = {
            "prompt": new_prompt,
            "completion": new_completion,
            "total": new_total,
            "limit": self.global_hard_limit,
            "utilization_pct": round(
                (new_total / self.global_hard_limit) * 100, 2
            ) if self.global_hard_limit > 0 else 0,
            "halted": False,
        }

        # Check hard limit
        if new_total >= self.global_hard_limit:
            await self._trigger_halt()
            result["halted"] = True
            logger.critical(
                "GLOBAL TOKEN HARD LIMIT BREACHED: %d/%d — HALT triggered",
                new_total, self.global_hard_limit,
            )
            raise CircuitBreakerTripped(
                f"Global token limit breached: {new_total}/{self.global_hard_limit}"
            )

        # Warn at 80%
        if new_total >= self.global_hard_limit * 0.8:
            logger.warning(
                "Global token usage at %.1f%%: %d/%d",
                result["utilization_pct"], new_total, self.global_hard_limit,
            )

        return result

    async def get_global_usage(self) -> dict:
        """Get current global token usage."""
        pipe = self._redis.pipeline()
        pipe.get(_GLOBAL_PROMPT_KEY)
        pipe.get(_GLOBAL_COMPLETION_KEY)
        pipe.get(_GLOBAL_COUNTER_KEY)
        pipe.get(_HALT_FLAG_KEY)
        results = await pipe.execute()

        return {
            "prompt": int(results[0] or 0),
            "completion": int(results[1] or 0),
            "total": int(results[2] or 0),
            "limit": self.global_hard_limit,
            "halted": bool(results[3]),
        }

    async def is_halted(self) -> bool:
        """Check if the system is in HALT state due to token exhaustion."""
        flag = await self._redis.get(_HALT_FLAG_KEY)
        return bool(flag)

    # ------------------------------------------------------------------
    # HALT / RESUME
    # ------------------------------------------------------------------

    async def _trigger_halt(self) -> None:
        """Set the global HALT flag and write audit log."""
        await self._redis.set(_HALT_FLAG_KEY, str(int(time.time() * 1000)))
        logger.critical("System HALT flag activated — token budget exhausted")

    async def reset_budget(
        self,
        new_limit: Optional[int] = None,
    ) -> None:
        """Reset global budget (requires human confirmation in production).

        Args:
            new_limit: If provided, update the global hard limit.
        """
        pipe = self._redis.pipeline()
        pipe.delete(_GLOBAL_COUNTER_KEY)
        pipe.delete(_GLOBAL_PROMPT_KEY)
        pipe.delete(_GLOBAL_COMPLETION_KEY)
        pipe.delete(_HALT_FLAG_KEY)
        await pipe.execute()

        if new_limit is not None:
            self.global_hard_limit = new_limit

        logger.info(
            "Global budget reset. New limit: %d", self.global_hard_limit
        )

    async def reset_agent_budget(self, agent_id: str) -> None:
        """Reset a single agent's soft budget counter."""
        key = f"{_AGENT_BUDGET_PREFIX}{agent_id}"
        await self._redis.delete(key)
        logger.info("Agent %s budget reset", agent_id)
