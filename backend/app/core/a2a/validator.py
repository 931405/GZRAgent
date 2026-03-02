"""
A2A Message Validation Pipeline.

Implements the 6-level validation order from design.md Section 3.2:
  1. Schema validation (version, required fields, types)
  2. Security validation (signature, token, nonce anti-replay)
  3. TTL validation (reject expired messages)
  4. Idempotency validation (message_id deduplication)
  5. Session consistency (session_version vs Registry)
  6. Business validation (grounding, parameter completeness)
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Any, Optional

import redis.asyncio as redis

from app.models.a2a import A2AMessage, A2AAckResponse
from app.models.errors import AckType, ErrorCode
from app.core.anp.registry import SessionRegistry

logger = logging.getLogger(__name__)

_NONCE_PREFIX = "pdmaws:nonce:"
_IDEMPOTENCY_PREFIX = "pdmaws:idempotent:"
_NONCE_TTL_DEFAULT = 86400  # 24 hours
_IDEMPOTENCY_TTL = 86400    # 24 hours


class ValidationError(Exception):
    """Raised when a validation step fails."""
    def __init__(self, error_code: ErrorCode, detail: str, retryable: bool = False):
        self.error_code = error_code
        self.detail = detail
        self.retryable = retryable
        super().__init__(f"{error_code.value}: {detail}")


class A2AValidator:
    """6-level validation pipeline for incoming A2A messages.

    Each level returns early on failure with the appropriate
    NACK type (RETRYABLE or FATAL).
    """

    def __init__(
        self,
        redis_client: redis.Redis,
        session_registry: SessionRegistry,
        hmac_secret: str = "",
    ) -> None:
        self._redis = redis_client
        self._registry = session_registry
        self._hmac_secret = hmac_secret

    async def validate(
        self, message: A2AMessage
    ) -> A2AAckResponse:
        """Run the full 6-level validation pipeline.

        Returns ACK on success, NACK on failure.
        """
        try:
            # Level 1: Schema validation
            self._validate_schema(message)

            # Level 2: Security validation
            await self._validate_security(message)

            # Level 3: TTL validation
            self._validate_ttl(message)

            # Level 4: Idempotency validation
            await self._validate_idempotency(message)

            # Level 5: Session consistency
            await self._validate_session(message)

            # Level 6: Business validation
            self._validate_business(message)

            return A2AAckResponse(
                original_message_id=message.meta.message_id,
                ack_type=AckType.ACK.value,
                timestamp_ms=int(time.time() * 1000),
            )

        except ValidationError as e:
            ack_type = (
                AckType.NACK_RETRYABLE.value
                if e.retryable
                else AckType.NACK_FATAL.value
            )
            logger.warning(
                "Validation failed for msg %s: %s (%s)",
                message.meta.message_id, e.error_code.value, e.detail,
            )
            return A2AAckResponse(
                original_message_id=message.meta.message_id,
                ack_type=ack_type,
                error_code=e.error_code.value,
                error_detail=e.detail,
                timestamp_ms=int(time.time() * 1000),
            )

    # -- Level 1: Schema --
    def _validate_schema(self, message: A2AMessage) -> None:
        """Validate schema version and required fields."""
        if message.meta.schema_version != "a2a.v1":
            raise ValidationError(
                ErrorCode.ERR_SCHEMA_INVALID,
                f"Unsupported schema version: {message.meta.schema_version}",
            )
        if not message.route.source_agent:
            raise ValidationError(
                ErrorCode.ERR_SCHEMA_INVALID,
                "Missing source_agent",
            )
        if not message.route.target_agent:
            raise ValidationError(
                ErrorCode.ERR_SCHEMA_INVALID,
                "Missing target_agent",
            )

    # -- Level 2: Security --
    async def _validate_security(self, message: A2AMessage) -> None:
        """Validate signature and anti-replay nonce."""
        sec = message.security

        # Nonce anti-replay check
        if sec.nonce:
            nonce_key = f"{_NONCE_PREFIX}{sec.nonce}"
            exists = await self._redis.exists(nonce_key)
            if exists:
                raise ValidationError(
                    ErrorCode.ERR_REPLAY_DETECTED,
                    f"Nonce already used: {sec.nonce}",
                )
            # Store nonce with TTL
            ttl = sec.nonce_ttl_ms // 1000 or _NONCE_TTL_DEFAULT
            await self._redis.setex(nonce_key, ttl, "1")

        # HMAC signature check (if secret configured)
        if self._hmac_secret and sec.signature:
            expected = self._compute_signature(message)
            if not hmac.compare_digest(sec.signature, expected):
                raise ValidationError(
                    ErrorCode.ERR_AUTH_INVALID,
                    "HMAC signature mismatch",
                )

    def _compute_signature(self, message: A2AMessage) -> str:
        """Compute HMAC-SHA256 signature for a message."""
        # Sign over key fields to prevent tampering
        payload = (
            f"{message.meta.message_id}"
            f"{message.meta.timestamp_ms}"
            f"{message.route.source_agent}"
            f"{message.route.target_agent}"
            f"{message.route.intent.value}"
        )
        return hmac.new(
            self._hmac_secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

    # -- Level 3: TTL --
    def _validate_ttl(self, message: A2AMessage) -> None:
        """Reject expired messages."""
        now_ms = int(time.time() * 1000)
        age = now_ms - message.meta.timestamp_ms
        if age > message.meta.ttl_ms:
            raise ValidationError(
                ErrorCode.ERR_TIMEOUT,
                f"Message expired: age={age}ms, ttl={message.meta.ttl_ms}ms",
                retryable=False,
            )

    # -- Level 4: Idempotency --
    async def _validate_idempotency(self, message: A2AMessage) -> None:
        """Deduplicate messages by message_id or idempotency_key."""
        dedup_key = message.meta.idempotency_key or message.meta.message_id
        redis_key = f"{_IDEMPOTENCY_PREFIX}{dedup_key}"

        exists = await self._redis.exists(redis_key)
        if exists:
            raise ValidationError(
                ErrorCode.ERR_REPLAY_DETECTED,
                f"Duplicate message: {dedup_key}",
                retryable=False,
            )
        # Mark as seen with TTL
        await self._redis.setex(redis_key, _IDEMPOTENCY_TTL, "1")

    # -- Level 5: Session consistency --
    async def _validate_session(self, message: A2AMessage) -> None:
        """Check session_version against SessionRegistry."""
        session = await self._registry.get_session(message.session.session_id)
        if session is None:
            # Unknown session — may be new, allow through
            return

        if message.session.session_version < session.session_version:
            raise ValidationError(
                ErrorCode.ERR_SESSION_STALE,
                f"Stale session version: msg has v{message.session.session_version}, "
                f"registry has v{session.session_version}",
                retryable=True,
            )

    # -- Level 6: Business --
    def _validate_business(self, message: A2AMessage) -> None:
        """Validate business-level constraints (grounding, etc.)."""
        # For intents that require grounding, check references exist
        grounding_required_intents = {
            "EVIDENCE_RESPONSE",
            "REVIEW_FEEDBACK",
            "REQUEST_DRAFT_PATCH",
        }
        if (
            message.route.intent.value in grounding_required_intents
            and not message.payload.context_grounding
        ):
            raise ValidationError(
                ErrorCode.ERR_GROUNDING_NOT_FOUND,
                f"Intent {message.route.intent.value} requires context_grounding",
                retryable=False,
            )
