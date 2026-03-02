"""
ACP Unified State Machine.

Implements the Agent Control Protocol state machine that governs the
lifecycle of every agent's task execution.

State flow (design.md Section 7.1):
    IDLE -> PLAN -> EXECUTE -> VERIFY -> EMIT -> WAIT -> DONE
    Any state + HALT -> INTERRUPTED
    VERIFY fail blocks EMIT
    ERROR consecutive > threshold -> auto-report to ANP

Rules:
  1. HALT from any state -> INTERRUPTED (no exceptions)
  2. VERIFY must pass before EMIT
  3. Consecutive ERRORs above threshold -> auto ANP escalation
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AgentState(str, Enum):
    """ACP unified agent states."""
    IDLE = "IDLE"
    PLAN = "PLAN"
    EXECUTE = "EXECUTE"
    VERIFY = "VERIFY"
    EMIT = "EMIT"
    WAIT = "WAIT"
    DONE = "DONE"
    ERROR = "ERROR"
    INTERRUPTED = "INTERRUPTED"


# Valid transitions (from -> set of allowed to)
VALID_AGENT_TRANSITIONS: dict[AgentState, set[AgentState]] = {
    AgentState.IDLE: {AgentState.PLAN, AgentState.INTERRUPTED},
    AgentState.PLAN: {AgentState.EXECUTE, AgentState.ERROR, AgentState.INTERRUPTED},
    AgentState.EXECUTE: {AgentState.VERIFY, AgentState.ERROR, AgentState.INTERRUPTED},
    AgentState.VERIFY: {
        AgentState.EMIT,      # verify passed
        AgentState.PLAN,      # verify failed -> re-plan
        AgentState.EXECUTE,   # verify failed -> re-execute
        AgentState.ERROR,
        AgentState.INTERRUPTED,
    },
    AgentState.EMIT: {AgentState.WAIT, AgentState.DONE, AgentState.ERROR, AgentState.INTERRUPTED},
    AgentState.WAIT: {AgentState.IDLE, AgentState.PLAN, AgentState.ERROR, AgentState.INTERRUPTED},
    AgentState.DONE: set(),  # terminal
    AgentState.ERROR: {
        AgentState.IDLE,    # retry from scratch
        AgentState.PLAN,    # retry from plan
        AgentState.INTERRUPTED,
    },
    AgentState.INTERRUPTED: set(),  # terminal (only RESUME can restart)
}


class StateTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""


class AgentStateMachine:
    """Manages the lifecycle state of a single agent.

    Features:
    - Enforces valid state transitions
    - HALT signal always transitions to INTERRUPTED
    - Tracks consecutive errors for ANP escalation
    - Supports transition hooks (before/after callbacks)
    """

    def __init__(
        self,
        agent_id: str,
        max_consecutive_errors: int = 3,
    ) -> None:
        self.agent_id = agent_id
        self.state = AgentState.IDLE
        self.max_consecutive_errors = max_consecutive_errors
        self._consecutive_errors = 0
        self._transition_history: list[dict[str, Any]] = []
        self._before_hooks: list[Callable] = []
        self._after_hooks: list[Callable] = []

    @property
    def is_terminal(self) -> bool:
        """Check if the agent is in a terminal state."""
        return self.state in (AgentState.DONE, AgentState.INTERRUPTED)

    @property
    def consecutive_errors(self) -> int:
        return self._consecutive_errors

    @property
    def should_escalate(self) -> bool:
        """Check if consecutive errors exceed threshold for ANP escalation."""
        return self._consecutive_errors >= self.max_consecutive_errors

    def transition(self, target: AgentState) -> AgentState:
        """Attempt to transition to a new state.

        Args:
            target: Desired target state.

        Returns:
            The new state after transition.

        Raises:
            StateTransitionError: If the transition is not valid.
        """
        old_state = self.state

        # Rule 1: HALT always goes to INTERRUPTED
        if target == AgentState.INTERRUPTED:
            self._do_transition(old_state, AgentState.INTERRUPTED)
            return self.state

        # Validate transition
        allowed = VALID_AGENT_TRANSITIONS.get(self.state, set())
        if target not in allowed:
            raise StateTransitionError(
                f"Agent {self.agent_id}: invalid transition "
                f"{self.state} -> {target}. "
                f"Allowed: {sorted(s.value for s in allowed)}"
            )

        # Rule 3: Track consecutive errors
        if target == AgentState.ERROR:
            self._consecutive_errors += 1
            if self.should_escalate:
                logger.warning(
                    "Agent %s: %d consecutive errors — flagged for ANP escalation",
                    self.agent_id, self._consecutive_errors,
                )
        else:
            self._consecutive_errors = 0

        self._do_transition(old_state, target)
        return self.state

    def _do_transition(
        self, old_state: AgentState, new_state: AgentState
    ) -> None:
        """Execute the transition with hooks."""
        # Before hooks
        for hook in self._before_hooks:
            hook(self.agent_id, old_state, new_state)

        self.state = new_state

        # Record history
        self._transition_history.append({
            "from": old_state.value,
            "to": new_state.value,
        })

        # After hooks
        for hook in self._after_hooks:
            hook(self.agent_id, old_state, new_state)

        logger.debug(
            "Agent %s: %s -> %s",
            self.agent_id, old_state.value, new_state.value,
        )

    def halt(self) -> None:
        """Receive HALT signal — immediately transition to INTERRUPTED.

        Rule: Any state + HALT -> INTERRUPTED (design.md §7.1 rule 1).
        """
        self.transition(AgentState.INTERRUPTED)

    def can_emit(self) -> bool:
        """Check if the agent is in VERIFY state and can proceed to EMIT.

        Rule 2: VERIFY must pass before EMIT (design.md §7.1 rule 2).
        """
        return self.state == AgentState.VERIFY

    def reset(self) -> None:
        """Reset the state machine to IDLE (for reuse after INTERRUPTED)."""
        self.state = AgentState.IDLE
        self._consecutive_errors = 0
        logger.info("Agent %s: state machine reset to IDLE", self.agent_id)

    def add_before_hook(self, hook: Callable) -> None:
        """Add a hook called before each transition.

        Signature: hook(agent_id, old_state, new_state)
        """
        self._before_hooks.append(hook)

    def add_after_hook(self, hook: Callable) -> None:
        """Add a hook called after each transition.

        Signature: hook(agent_id, old_state, new_state)
        """
        self._after_hooks.append(hook)

    def get_history(self) -> list[dict[str, Any]]:
        """Get the full transition history."""
        return list(self._transition_history)
