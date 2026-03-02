"""
ANP Session Registry Models.

Defines the session state machine and SessionEntry — the single
authoritative record of every active session.

Ref: design.md Sections 4.0–4.3
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class SessionState(str, Enum):
    """Session lifecycle states.

    State transitions:
        INIT -> RUNNING -> NEGOTIATING -> RUNNING  (consensus)
                                       -> ARBITRATION  (deadlock)
        ARBITRATION -> RUNNING  (resolved)
                    -> HALTED   (human escalation)
        RUNNING -> DEGRADED  (grounding unavailable)
        DEGRADED -> RUNNING  (service restored)
        RUNNING -> HALTED  (token circuit breaker)
        HALTED -> RUNNING  (budget reset)
              -> FAILED   (human abort)
        RUNNING -> COMPLETED  (all done)

    Ref: design.md Section 4.1
    """
    INIT = "INIT"
    RUNNING = "RUNNING"
    NEGOTIATING = "NEGOTIATING"
    ARBITRATION = "ARBITRATION"
    DEGRADED = "DEGRADED"
    HALTED = "HALTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


# Valid state transitions (from -> set of allowed targets)
VALID_SESSION_TRANSITIONS: dict[SessionState, set[SessionState]] = {
    SessionState.INIT: {SessionState.RUNNING, SessionState.FAILED},
    SessionState.RUNNING: {
        SessionState.NEGOTIATING,
        SessionState.DEGRADED,
        SessionState.HALTED,
        SessionState.COMPLETED,
        SessionState.FAILED,
    },
    SessionState.NEGOTIATING: {
        SessionState.RUNNING,
        SessionState.ARBITRATION,
        SessionState.HALTED,
        SessionState.FAILED,
    },
    SessionState.ARBITRATION: {
        SessionState.RUNNING,
        SessionState.HALTED,
        SessionState.FAILED,
    },
    SessionState.DEGRADED: {
        SessionState.RUNNING,
        SessionState.HALTED,
        SessionState.FAILED,
    },
    SessionState.HALTED: {
        SessionState.RUNNING,
        SessionState.FAILED,
    },
    SessionState.COMPLETED: set(),  # terminal
    SessionState.FAILED: set(),      # terminal
}


class BudgetSnapshot(BaseModel):
    """Token budget snapshot at session level."""
    total_prompt_tokens: int = Field(default=0, ge=0)
    total_completion_tokens: int = Field(default=0, ge=0)
    budget_limit: int = Field(default=200_000, ge=0)
    utilization_pct: float = Field(default=0.0, ge=0.0, le=100.0)


class SessionEntry(BaseModel):
    """A single session record in the ANP SessionRegistry.

    This is the ONLY authoritative source for session state.
    All other layers carry read-only snapshots.

    Ref: design.md Section 4.1
    """
    session_id: str
    parent_session_id: str = Field(
        default="",
        description="Non-empty for child sessions in Map-Reduce tree",
    )
    sub_task_id: str = Field(
        default="",
        description="E.g. sec_intro, sec_method, sec_results",
    )
    session_version: int = Field(
        default=1,
        ge=1,
        description="Monotonically increasing; incremented on each state change",
    )
    state: SessionState = Field(
        default=SessionState.INIT,
    )
    participants: list[str] = Field(
        default_factory=list,
        description="List of agent IDs participating in this session",
    )
    turn_counter: int = Field(
        default=0,
        ge=0,
    )
    max_turns_allowed: int = Field(
        default=6,
        ge=1,
    )
    deadline_ms: int = Field(
        default=0,
        ge=0,
        description="Absolute deadline timestamp in ms (0 = no deadline)",
    )
    last_progress_ts: int = Field(
        default=0,
        ge=0,
        description="Timestamp of last meaningful progress",
    )
    conflict_counter: int = Field(
        default=0,
        ge=0,
        description="Number of conflicts encountered in this session",
    )
    budget_snapshot: BudgetSnapshot = Field(
        default_factory=BudgetSnapshot,
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Arbitrary session-level metadata",
    )

    def can_transition_to(self, target: SessionState) -> bool:
        """Check whether the transition from current state to target is valid."""
        return target in VALID_SESSION_TRANSITIONS.get(self.state, set())
