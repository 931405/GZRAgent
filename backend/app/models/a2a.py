"""
A2A (Agent-to-Agent) Protocol Message Models.

Complete implementation of the A2A message schema as defined in design.md Section 3.
Covers: meta, session, route, payload, control, telemetry, security blocks.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator
import uuid


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MessagePriority(str, Enum):
    """Message priority levels."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class AgentIntent(str, Enum):
    """Standardized intents for A2A communication.

    Each intent maps to a specific business action in the protocol.
    """
    # -- Task Management --
    REQUEST_TASK = "REQUEST_TASK"
    TASK_ACCEPTED = "TASK_ACCEPTED"
    TASK_REJECTED = "TASK_REJECTED"
    TASK_COMPLETED = "TASK_COMPLETED"
    SUB_TASK_READY = "SUB_TASK_READY"

    # -- Document Operations --
    REQUEST_DRAFT_PATCH = "REQUEST_DRAFT_PATCH"
    DRAFT_PATCH_APPLIED = "DRAFT_PATCH_APPLIED"
    DRAFT_INTEGRATED_READY = "DRAFT_INTEGRATED_READY"

    # -- Evidence & Research --
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"
    EVIDENCE_RESPONSE = "EVIDENCE_RESPONSE"
    REQUEST_DATA_ANALYSIS = "REQUEST_DATA_ANALYSIS"
    DATA_ANALYSIS_RESPONSE = "DATA_ANALYSIS_RESPONSE"

    # -- Diagram --
    REQUEST_DIAGRAM_GENERATION = "REQUEST_DIAGRAM_GENERATION"
    DIAGRAM_RESPONSE = "DIAGRAM_RESPONSE"

    # -- Review --
    REQUEST_REVIEW = "REQUEST_REVIEW"
    REVIEW_FEEDBACK = "REVIEW_FEEDBACK"

    # -- Format --
    REQUEST_FORMAT = "REQUEST_FORMAT"
    FORMAT_COMPLETED = "FORMAT_COMPLETED"

    # -- Arbitration --
    ARBITRATION_REQUEST = "ARBITRATION_REQUEST"
    ARBITRATION_DECISION = "ARBITRATION_DECISION"
    HUMAN_ESCALATION = "HUMAN_ESCALATION"

    # -- Control --
    HALT = "HALT"
    RESUME = "RESUME"
    COMPRESS_CONTEXT = "COMPRESS_CONTEXT"
    FORCE_UPDATE_DRAFT = "FORCE_UPDATE_DRAFT"
    INTERRUPT = "INTERRUPT"

    # -- Health --
    HEARTBEAT = "HEARTBEAT"
    STATUS_REPORT = "STATUS_REPORT"


class DegradeMode(str, Enum):
    """Degradation modes for controlled service deterioration."""
    NONE = "none"
    LOW_CONFIDENCE = "low_confidence"
    CACHED_ONLY = "cached_only"
    READONLY = "readonly"


# ---------------------------------------------------------------------------
# Sub-Models
# ---------------------------------------------------------------------------

class MessageMeta(BaseModel):
    """Message metadata block.

    Ref: design.md Section 3.1 → meta
    """
    message_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique message identifier (UUID v7 for temporal ordering)",
    )
    correlation_id: str = Field(
        ...,
        description="Root request ID for distributed tracing",
    )
    causation_id: str = Field(
        default="",
        description="Parent message ID (builds causation chain)",
    )
    timestamp_ms: int = Field(
        ...,
        description="Unix timestamp in milliseconds",
    )
    schema_version: str = Field(
        default="a2a.v1",
        description="Protocol schema version",
    )
    priority: MessagePriority = Field(
        default=MessagePriority.NORMAL,
    )
    ttl_ms: int = Field(
        default=30_000,
        ge=1000,
        le=300_000,
        description="Time-to-live in milliseconds",
    )
    requires_ack: bool = Field(
        default=True,
        description="Whether the receiver must send ACK/NACK",
    )
    idempotency_key: str = Field(
        default="",
        description="Optional business-level idempotency key",
    )


class SessionContext(BaseModel):
    """Session context snapshot carried in A2A messages.

    NOTE: This is a READ-ONLY snapshot. The authoritative state lives in
    ANP.SessionRegistry. Receiver must compare session_version.

    Ref: design.md Section 3.1 → session
    """
    session_id: str
    parent_session_id: str = Field(
        default="",
        description="Non-empty if this is a child session",
    )
    sub_task_id: str = Field(
        default="",
        description="Identifier for the sub-task within a Map-Reduce tree",
    )
    session_version: int = Field(
        ge=0,
        description="Monotonically increasing version; must match Registry",
    )
    current_turn: int = Field(
        ge=0,
        description="Current negotiation turn",
    )
    max_turns_allowed: int = Field(
        default=6,
        ge=1,
    )
    state_hint: str = Field(
        default="RUNNING",
        description="Hint about session state (snapshot, not authoritative)",
    )


class RouteInfo(BaseModel):
    """Routing information for message delivery.

    Ref: design.md Section 3.1 → route
    """
    source_agent: str = Field(
        ...,
        description="Sending agent identifier",
    )
    target_agent: str = Field(
        ...,
        description="Target agent identifier",
    )
    intent: AgentIntent = Field(
        ...,
        description="The semantic intent of this message",
    )
    reply_to: str = Field(
        default="",
        description="Queue/topic for reply routing",
    )


class DocumentPointer(BaseModel):
    """Pointer to a document in the Blackboard (no inline content).

    Ref: design.md Section 3.1 → payload.document_pointer
    """
    draft_id: str
    version_hash: str = Field(
        description="Baseline version hash for optimistic locking",
    )
    patch_operations: list[dict[str, Any]] = Field(
        default_factory=list,
        description="JSON Patch operations (RFC 6902)",
    )


class Payload(BaseModel):
    """Business payload.

    Ref: design.md Section 3.1 → payload
    """
    context_grounding: list[str] = Field(
        default_factory=list,
        description="Reference IDs for evidence/grounding verification",
    )
    document_pointer: Optional[DocumentPointer] = Field(
        default=None,
        description="Pointer to document in Blackboard",
    )
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Task-specific constraints",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Generic payload data",
    )


class ControlDirective(BaseModel):
    """Control directives for message handling.

    Ref: design.md Section 3.1 → control
    """
    timeout_ms: int = Field(
        default=15_000,
        ge=1000,
        description="Operation timeout",
    )
    requires_human_arbiter: bool = Field(
        default=False,
    )
    degrade_mode: DegradeMode = Field(
        default=DegradeMode.NONE,
    )


class Telemetry(BaseModel):
    """Telemetry data for observability.

    Ref: design.md Section 3.1 → telemetry
    """
    prompt_tokens_used: int = Field(default=0, ge=0)
    completion_tokens_used: int = Field(default=0, ge=0)
    model: str = Field(default="")
    latency_ms: int = Field(default=0, ge=0)


class SecurityInfo(BaseModel):
    """Security fields for authentication and integrity.

    Ref: design.md Section 3.1 → security
    """
    auth_type: str = Field(
        default="jwt",
        description="Authentication type (jwt, api_key, etc.)",
    )
    signature: str = Field(
        default="",
        description="HMAC-SHA256 signature of the message body",
    )
    nonce: str = Field(
        default="",
        description="Random nonce for anti-replay protection",
    )
    nonce_ttl_ms: int = Field(
        default=60_000,
        ge=1000,
        description="Nonce time-to-live",
    )


# ---------------------------------------------------------------------------
# Complete A2A Message
# ---------------------------------------------------------------------------

class A2AMessage(BaseModel):
    """Complete A2A Protocol Message.

    The top-level message exchanged between agents. Contains all 7 blocks.
    Ref: design.md Section 3.1
    """
    meta: MessageMeta
    session: SessionContext
    route: RouteInfo
    payload: Payload = Field(default_factory=Payload)
    control: ControlDirective = Field(default_factory=ControlDirective)
    telemetry: Telemetry = Field(default_factory=Telemetry)
    security: SecurityInfo = Field(default_factory=SecurityInfo)

    @field_validator("meta", mode="before")
    @classmethod
    def _ensure_message_id(cls, v: Any) -> Any:
        """Auto-generate message_id if not provided."""
        if isinstance(v, dict) and not v.get("message_id"):
            v["message_id"] = str(uuid.uuid4())
        return v


# ---------------------------------------------------------------------------
# ACK / NACK Response
# ---------------------------------------------------------------------------

class A2AAckResponse(BaseModel):
    """ACK/NACK response to an A2A message.

    Ref: design.md Section 3.3
    """
    original_message_id: str
    ack_type: str = Field(
        description="ACK | NACK_RETRYABLE | NACK_FATAL",
    )
    error_code: str = Field(
        default="",
        description="Error code if NACK",
    )
    error_detail: str = Field(
        default="",
        description="Human-readable error detail",
    )
    timestamp_ms: int = Field(
        ...,
        description="When this ACK was generated",
    )
