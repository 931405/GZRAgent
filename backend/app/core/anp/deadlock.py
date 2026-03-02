"""
Deadlock Detection Engine.

Detects suspected deadlocks using four independent trigger conditions.
When any condition fires, the session is transitioned to ARBITRATION.

Trigger conditions (design.md Section 4.2):
  1. turn_counter > max_turns_allowed
  2. last_progress_ts exceeds timeout threshold (2x timeout window)
  3. Same dispute bouncing between same participants > N times
  4. Same intent repeated N times in short window

Actions on detection:
  1. Session state → ARBITRATION
  2. Freeze normal writes
  3. Only PI_Agent arbitration messages allowed
  4. After arbitration: resume or terminate
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from app.models.session import SessionEntry, SessionState
from app.core.anp.registry import SessionRegistry

logger = logging.getLogger(__name__)

# Default thresholds
DEFAULT_PROGRESS_TIMEOUT_MS = 120_000  # 2 minutes
DEFAULT_DISPUTE_BOUNCE_LIMIT = 3
DEFAULT_INTENT_REPEAT_LIMIT = 5
DEFAULT_INTENT_WINDOW_MS = 60_000  # 1 minute


class DeadlockEvent:
    """Record of a detected deadlock condition."""

    def __init__(
        self,
        session_id: str,
        trigger: str,
        detail: str,
        timestamp_ms: int,
    ) -> None:
        self.session_id = session_id
        self.trigger = trigger
        self.detail = detail
        self.timestamp_ms = timestamp_ms

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "trigger": self.trigger,
            "detail": self.detail,
            "timestamp_ms": self.timestamp_ms,
        }


class DeadlockDetector:
    """Monitors sessions for suspected deadlocks.

    Uses four criteria (any one triggers detection):
      1. Turn overflow
      2. Progress stall
      3. Dispute bounce
      4. Intent repetition
    """

    def __init__(
        self,
        registry: SessionRegistry,
        progress_timeout_ms: int = DEFAULT_PROGRESS_TIMEOUT_MS,
        dispute_bounce_limit: int = DEFAULT_DISPUTE_BOUNCE_LIMIT,
        intent_repeat_limit: int = DEFAULT_INTENT_REPEAT_LIMIT,
        intent_window_ms: int = DEFAULT_INTENT_WINDOW_MS,
    ) -> None:
        self._registry = registry
        self.progress_timeout_ms = progress_timeout_ms
        self.dispute_bounce_limit = dispute_bounce_limit
        self.intent_repeat_limit = intent_repeat_limit
        self.intent_window_ms = intent_window_ms

        # In-memory tracking for dispute bounces and intent history
        # Key: session_id, Value: list of (source, target, intent, timestamp)
        self._intent_history: dict[str, list[dict]] = {}

    def record_intent(
        self,
        session_id: str,
        source_agent: str,
        target_agent: str,
        intent: str,
    ) -> None:
        """Record an intent for deadlock analysis."""
        if session_id not in self._intent_history:
            self._intent_history[session_id] = []

        self._intent_history[session_id].append({
            "source": source_agent,
            "target": target_agent,
            "intent": intent,
            "timestamp": int(time.time() * 1000),
        })

        # Trim old entries (keep last 100)
        if len(self._intent_history[session_id]) > 100:
            self._intent_history[session_id] = \
                self._intent_history[session_id][-100:]

    async def check_session(
        self, session_id: str
    ) -> Optional[DeadlockEvent]:
        """Run all deadlock checks on a session.

        Returns: DeadlockEvent if deadlock suspected, None otherwise.
        """
        entry = await self._registry.get_session(session_id)
        if entry is None:
            return None

        # Skip terminal or already arbitrating sessions
        if entry.state in (
            SessionState.COMPLETED,
            SessionState.FAILED,
            SessionState.ARBITRATION,
            SessionState.HALTED,
        ):
            return None

        now_ms = int(time.time() * 1000)

        # Check 1: Turn overflow
        event = self._check_turn_overflow(entry)
        if event:
            return event

        # Check 2: Progress stall
        event = self._check_progress_stall(entry, now_ms)
        if event:
            return event

        # Check 3: Dispute bounce
        event = self._check_dispute_bounce(session_id)
        if event:
            return event

        # Check 4: Intent repetition
        event = self._check_intent_repetition(session_id, now_ms)
        if event:
            return event

        return None

    def _check_turn_overflow(self, entry: SessionEntry) -> Optional[DeadlockEvent]:
        """Condition 1: turn_counter > max_turns_allowed."""
        if entry.turn_counter > entry.max_turns_allowed:
            return DeadlockEvent(
                session_id=entry.session_id,
                trigger="TURN_OVERFLOW",
                detail=(
                    f"Turn {entry.turn_counter} exceeds max {entry.max_turns_allowed}"
                ),
                timestamp_ms=int(time.time() * 1000),
            )
        return None

    def _check_progress_stall(
        self, entry: SessionEntry, now_ms: int
    ) -> Optional[DeadlockEvent]:
        """Condition 2: No progress beyond 2x timeout window."""
        if entry.last_progress_ts <= 0:
            return None

        elapsed = now_ms - entry.last_progress_ts
        if elapsed > self.progress_timeout_ms:
            return DeadlockEvent(
                session_id=entry.session_id,
                trigger="PROGRESS_STALL",
                detail=(
                    f"No progress for {elapsed}ms "
                    f"(threshold: {self.progress_timeout_ms}ms)"
                ),
                timestamp_ms=now_ms,
            )
        return None

    def _check_dispute_bounce(
        self, session_id: str
    ) -> Optional[DeadlockEvent]:
        """Condition 3: Same dispute bouncing between same participants > N times."""
        history = self._intent_history.get(session_id, [])
        if len(history) < self.dispute_bounce_limit * 2:
            return None

        # Look for ping-pong pattern between same pair
        recent = history[-self.dispute_bounce_limit * 2:]
        pair_counts: dict[tuple, int] = {}

        for entry in recent:
            pair = (
                min(entry["source"], entry["target"]),
                max(entry["source"], entry["target"]),
            )
            pair_counts[pair] = pair_counts.get(pair, 0) + 1

        for pair, count in pair_counts.items():
            if count >= self.dispute_bounce_limit * 2:
                return DeadlockEvent(
                    session_id=session_id,
                    trigger="DISPUTE_BOUNCE",
                    detail=(
                        f"Agents {pair[0]} <-> {pair[1]} "
                        f"bounced {count} times"
                    ),
                    timestamp_ms=int(time.time() * 1000),
                )
        return None

    def _check_intent_repetition(
        self, session_id: str, now_ms: int
    ) -> Optional[DeadlockEvent]:
        """Condition 4: Same intent repeated N times in short window."""
        history = self._intent_history.get(session_id, [])
        window_start = now_ms - self.intent_window_ms

        # Filter to recent window
        recent_intents = [
            h["intent"] for h in history
            if h["timestamp"] >= window_start
        ]

        # Count occurrences
        intent_counts: dict[str, int] = {}
        for intent in recent_intents:
            intent_counts[intent] = intent_counts.get(intent, 0) + 1

        for intent, count in intent_counts.items():
            if count >= self.intent_repeat_limit:
                return DeadlockEvent(
                    session_id=session_id,
                    trigger="INTENT_REPETITION",
                    detail=(
                        f"Intent '{intent}' repeated {count} times "
                        f"in {self.intent_window_ms}ms window"
                    ),
                    timestamp_ms=now_ms,
                )
        return None

    async def handle_deadlock(
        self, event: DeadlockEvent
    ) -> SessionEntry:
        """Handle a detected deadlock by transitioning to ARBITRATION.

        Actions:
          1. Transition session state to ARBITRATION
          2. Log audit event
        """
        logger.warning(
            "DEADLOCK DETECTED in session %s: trigger=%s, detail=%s",
            event.session_id, event.trigger, event.detail,
        )

        entry = await self._registry.transition_state(
            event.session_id, SessionState.ARBITRATION
        )

        return entry

    def clear_history(self, session_id: str) -> None:
        """Clear intent history for a session (after resolution)."""
        self._intent_history.pop(session_id, None)
