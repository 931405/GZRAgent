"""
Unified Error Codes for PD-MAWS A2A Protocol.

Ref: design.md Section 3.4
"""
from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """Standardized error codes used across all protocol layers."""

    # -- Schema & Validation --
    ERR_SCHEMA_INVALID = "ERR_SCHEMA_INVALID"

    # -- Security --
    ERR_AUTH_INVALID = "ERR_AUTH_INVALID"
    ERR_REPLAY_DETECTED = "ERR_REPLAY_DETECTED"

    # -- Session --
    ERR_SESSION_STALE = "ERR_SESSION_STALE"

    # -- Grounding --
    ERR_GROUNDING_NOT_FOUND = "ERR_GROUNDING_NOT_FOUND"
    ERR_GROUNDING_UNAVAILABLE = "ERR_GROUNDING_UNAVAILABLE"

    # -- Operational --
    ERR_TIMEOUT = "ERR_TIMEOUT"
    ERR_DEADLOCK_SUSPECTED = "ERR_DEADLOCK_SUSPECTED"
    ERR_RATE_LIMITED = "ERR_RATE_LIMITED"

    # -- Policy --
    ERR_POLICY_VIOLATION = "ERR_POLICY_VIOLATION"

    # -- Document --
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    ERR_DOCUMENT_LOCKED = "ERR_DOCUMENT_LOCKED"


class AckType(str, Enum):
    """ACK/NACK semantics for A2A messages.

    Ref: design.md Section 3.3
    """
    ACK = "ACK"
    NACK_RETRYABLE = "NACK_RETRYABLE"
    NACK_FATAL = "NACK_FATAL"
