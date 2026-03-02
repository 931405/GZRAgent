"""
ANP SessionRegistry — the SINGLE authoritative source of session state.

All session state mutations go through this registry. Other layers carry
read-only snapshots and must compare session_version before acting.

Storage strategy:
  - Runtime: Redis Hash for low-latency reads/writes
  - Archive: PostgreSQL for durability and history

Ref: design.md Section 4.1
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

import redis.asyncio as redis

from app.models.session import (
    BudgetSnapshot,
    SessionEntry,
    SessionState,
    VALID_SESSION_TRANSITIONS,
)

logger = logging.getLogger(__name__)

# Redis key prefix
_SESSION_KEY_PREFIX = "pdmaws:session:"
_SESSION_INDEX_KEY = "pdmaws:session_index"


class SessionTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""


class SessionVersionConflict(Exception):
    """Raised when session_version doesn't match (optimistic locking)."""


class SessionRegistry:
    """Authoritative session state manager.

    Global Invariant (design.md §1.2.1):
        ANP.SessionRegistry is THE ONLY authoritative source for session state.
        Other layers may only read snapshots — never write directly.
    """

    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _key(session_id: str) -> str:
        return f"{_SESSION_KEY_PREFIX}{session_id}"

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create_session(
        self,
        session_id: str,
        parent_session_id: str = "",
        sub_task_id: str = "",
        participants: Optional[list[str]] = None,
        max_turns: int = 6,
        budget_limit: int = 200_000,
    ) -> SessionEntry:
        """Create a new session in INIT state."""
        now_ms = int(time.time() * 1000)
        entry = SessionEntry(
            session_id=session_id,
            parent_session_id=parent_session_id,
            sub_task_id=sub_task_id,
            session_version=1,
            state=SessionState.INIT,
            participants=participants or [],
            max_turns_allowed=max_turns,
            last_progress_ts=now_ms,
            budget_snapshot=BudgetSnapshot(budget_limit=budget_limit),
        )
        key = self._key(session_id)
        # Store as JSON in Redis Hash
        await self._redis.hset(key, mapping={"data": entry.model_dump_json()})  # type: ignore[arg-type]
        # Add to index
        await self._redis.sadd(_SESSION_INDEX_KEY, session_id)

        logger.info(
            "Session created: %s (parent=%s, sub_task=%s)",
            session_id, parent_session_id, sub_task_id,
        )
        return entry

    async def get_session(self, session_id: str) -> Optional[SessionEntry]:
        """Retrieve the current session state."""
        key = self._key(session_id)
        raw = await self._redis.hget(key, "data")
        if raw is None:
            return None
        return SessionEntry.model_validate_json(raw)

    async def list_sessions(self) -> list[str]:
        """List all active session IDs."""
        members = await self._redis.smembers(_SESSION_INDEX_KEY)
        return [m.decode() if isinstance(m, bytes) else m for m in members]

    async def get_child_sessions(self, parent_id: str) -> list[SessionEntry]:
        """Get all child sessions of a parent (Map-Reduce tree)."""
        all_ids = await self.list_sessions()
        children = []
        for sid in all_ids:
            entry = await self.get_session(sid)
            if entry and entry.parent_session_id == parent_id:
                children.append(entry)
        return children

    # ------------------------------------------------------------------
    # State transitions (atomic)
    # ------------------------------------------------------------------

    async def transition_state(
        self,
        session_id: str,
        target_state: SessionState,
        expected_version: Optional[int] = None,
    ) -> SessionEntry:
        """Atomically transition session state.

        1. Validate transition legality.
        2. Optionally check optimistic locking via expected_version.
        3. Increment session_version.
        4. Update last_progress_ts.

        Args:
            session_id: Target session.
            target_state: Desired new state.
            expected_version: If provided, current version must match.

        Raises:
            SessionTransitionError: Invalid transition.
            SessionVersionConflict: Version mismatch.
        """
        entry = await self.get_session(session_id)
        if entry is None:
            raise SessionTransitionError(f"Session not found: {session_id}")

        # Optimistic locking
        if expected_version is not None and entry.session_version != expected_version:
            raise SessionVersionConflict(
                f"Expected version {expected_version}, "
                f"got {entry.session_version} for session {session_id}"
            )

        # Validate transition
        if not entry.can_transition_to(target_state):
            raise SessionTransitionError(
                f"Invalid transition: {entry.state} -> {target_state} "
                f"for session {session_id}"
            )

        # Apply transition
        entry.state = target_state
        entry.session_version += 1
        entry.last_progress_ts = int(time.time() * 1000)

        # Persist
        key = self._key(session_id)
        await self._redis.hset(key, mapping={"data": entry.model_dump_json()})  # type: ignore[arg-type]

        logger.info(
            "Session %s transitioned to %s (v%d)",
            session_id, target_state.value, entry.session_version,
        )
        return entry

    # ------------------------------------------------------------------
    # Turn management
    # ------------------------------------------------------------------

    async def increment_turn(self, session_id: str) -> SessionEntry:
        """Increment the turn counter and update progress timestamp."""
        entry = await self.get_session(session_id)
        if entry is None:
            raise ValueError(f"Session not found: {session_id}")

        entry.turn_counter += 1
        entry.session_version += 1
        entry.last_progress_ts = int(time.time() * 1000)

        key = self._key(session_id)
        await self._redis.hset(key, mapping={"data": entry.model_dump_json()})  # type: ignore[arg-type]
        return entry

    # ------------------------------------------------------------------
    # Budget tracking
    # ------------------------------------------------------------------

    async def update_budget(
        self,
        session_id: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
    ) -> SessionEntry:
        """Update token budget snapshot for a session."""
        entry = await self.get_session(session_id)
        if entry is None:
            raise ValueError(f"Session not found: {session_id}")

        entry.budget_snapshot.total_prompt_tokens += prompt_tokens
        entry.budget_snapshot.total_completion_tokens += completion_tokens
        total = (
            entry.budget_snapshot.total_prompt_tokens
            + entry.budget_snapshot.total_completion_tokens
        )
        if entry.budget_snapshot.budget_limit > 0:
            entry.budget_snapshot.utilization_pct = round(
                (total / entry.budget_snapshot.budget_limit) * 100, 2
            )

        key = self._key(session_id)
        await self._redis.hset(key, mapping={"data": entry.model_dump_json()})  # type: ignore[arg-type]
        return entry

    # ------------------------------------------------------------------
    # Conflict tracking
    # ------------------------------------------------------------------

    async def increment_conflict(self, session_id: str) -> SessionEntry:
        """Increment the conflict counter."""
        entry = await self.get_session(session_id)
        if entry is None:
            raise ValueError(f"Session not found: {session_id}")

        entry.conflict_counter += 1
        entry.session_version += 1

        key = self._key(session_id)
        await self._redis.hset(key, mapping={"data": entry.model_dump_json()})  # type: ignore[arg-type]
        return entry

    # ------------------------------------------------------------------
    # Participant management
    # ------------------------------------------------------------------

    async def add_participant(self, session_id: str, agent_id: str) -> SessionEntry:
        """Add an agent to the session participants."""
        entry = await self.get_session(session_id)
        if entry is None:
            raise ValueError(f"Session not found: {session_id}")

        if agent_id not in entry.participants:
            entry.participants.append(agent_id)
            entry.session_version += 1
            key = self._key(session_id)
            await self._redis.hset(key, mapping={"data": entry.model_dump_json()})  # type: ignore[arg-type]

        return entry

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def delete_session(self, session_id: str) -> bool:
        """Remove a session (for cleanup; production would archive to PG)."""
        key = self._key(session_id)
        deleted = await self._redis.delete(key)
        await self._redis.srem(_SESSION_INDEX_KEY, session_id)
        return deleted > 0
