"""
Message Bus — dual-channel communication infrastructure.

Channel classification (design.md Section 5):
  - Control Plane (MUST NOT LOSE): Redis Streams with ACK, retry, DLQ
  - Data Plane (BEST EFFORT): Redis Pub/Sub for lightweight notifications

Retry strategy (design.md Section 5.2):
  - Exponential backoff: base=200ms, factor=2, max=5s
  - Max retries: 5
  - Overflow → DLQ + alert
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Callable, Coroutine, Optional

import redis.asyncio as redis

from app.models.a2a import A2AMessage

logger = logging.getLogger(__name__)

# Redis key prefixes
_STREAM_PREFIX = "pdmaws:stream:"
_DLQ_PREFIX = "pdmaws:dlq:"
_PUBSUB_PREFIX = "pdmaws:pubsub:"
_CONSUMER_GROUP = "pdmaws_agents"

# Retry config (design.md §5.2)
RETRY_BASE_MS = 200
RETRY_FACTOR = 2
RETRY_MAX_MS = 5000
MAX_RETRIES = 5


class MessageBus:
    """Dual-channel message bus for A2A communication.

    Control Plane: Redis Streams — persistent, ACK-based, with DLQ.
    Data Plane: Redis Pub/Sub — fire-and-forget notifications.
    """

    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client
        self._pubsub = redis_client.pubsub()
        self._running = False

    # ==================================================================
    # Control Plane (Redis Streams) — messages MUST NOT be lost
    # ==================================================================

    async def ensure_stream_group(self, stream_name: str) -> None:
        """Create a consumer group for a stream if it doesn't exist."""
        key = f"{_STREAM_PREFIX}{stream_name}"
        try:
            await self._redis.xgroup_create(
                key, _CONSUMER_GROUP, id="0", mkstream=True
            )
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def publish_control(
        self,
        stream_name: str,
        message: A2AMessage,
    ) -> str:
        """Publish a control-plane message to a Redis Stream.

        Returns: The stream message ID.
        """
        key = f"{_STREAM_PREFIX}{stream_name}"
        data = {
            "payload": message.model_dump_json(),
            "message_id": message.meta.message_id,
            "intent": message.route.intent.value,
            "timestamp": str(int(time.time() * 1000)),
        }
        msg_id = await self._redis.xadd(key, data)  # type: ignore
        logger.debug(
            "Control message published: stream=%s, msg_id=%s, intent=%s",
            stream_name, msg_id, message.route.intent.value,
        )
        return msg_id.decode() if isinstance(msg_id, bytes) else msg_id

    async def consume_control(
        self,
        stream_name: str,
        consumer_id: str,
        handler: Callable[[A2AMessage], Coroutine[Any, Any, bool]],
        batch_size: int = 10,
        block_ms: int = 5000,
    ) -> None:
        """Consume control-plane messages from a stream.

        Args:
            stream_name: Stream to consume from.
            consumer_id: Unique consumer identifier.
            handler: Async function; returns True on success, False to retry.
            batch_size: Max messages per read.
            block_ms: Block timeout for XREADGROUP.
        """
        key = f"{_STREAM_PREFIX}{stream_name}"
        await self.ensure_stream_group(stream_name)

        self._running = True
        while self._running:
            try:
                messages = await self._redis.xreadgroup(
                    groupname=_CONSUMER_GROUP,
                    consumername=consumer_id,
                    streams={key: ">"},
                    count=batch_size,
                    block=block_ms,
                )

                if not messages:
                    continue

                for _, msg_list in messages:
                    for msg_id, fields in msg_list:
                        payload_raw = fields.get(b"payload") or fields.get("payload")
                        if payload_raw is None:
                            await self._redis.xack(key, _CONSUMER_GROUP, msg_id)
                            continue

                        if isinstance(payload_raw, bytes):
                            payload_raw = payload_raw.decode()

                        try:
                            a2a_msg = A2AMessage.model_validate_json(payload_raw)
                        except Exception as e:
                            logger.error("Failed to parse message %s: %s", msg_id, e)
                            await self._move_to_dlq(stream_name, msg_id, fields, str(e))
                            await self._redis.xack(key, _CONSUMER_GROUP, msg_id)
                            continue

                        success = await self._handle_with_retry(handler, a2a_msg)

                        if success:
                            await self._redis.xack(key, _CONSUMER_GROUP, msg_id)
                        else:
                            await self._move_to_dlq(
                                stream_name, msg_id, fields, "Max retries exceeded"
                            )
                            await self._redis.xack(key, _CONSUMER_GROUP, msg_id)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Consumer error on stream %s: %s", stream_name, e)
                await asyncio.sleep(1)

    async def _handle_with_retry(
        self,
        handler: Callable[[A2AMessage], Coroutine[Any, Any, bool]],
        message: A2AMessage,
    ) -> bool:
        """Execute handler with exponential backoff retry."""
        delay_ms = RETRY_BASE_MS
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                result = await handler(message)
                if result:
                    return True
            except Exception as e:
                logger.warning(
                    "Handler attempt %d/%d failed for msg %s: %s",
                    attempt, MAX_RETRIES, message.meta.message_id, e,
                )

            if attempt < MAX_RETRIES:
                await asyncio.sleep(delay_ms / 1000.0)
                delay_ms = min(delay_ms * RETRY_FACTOR, RETRY_MAX_MS)

        return False

    async def _move_to_dlq(
        self,
        stream_name: str,
        msg_id: Any,
        fields: dict,
        reason: str,
    ) -> None:
        """Move a failed message to the Dead Letter Queue."""
        dlq_key = f"{_DLQ_PREFIX}{stream_name}"
        dlq_entry = {
            "original_msg_id": str(msg_id),
            "reason": reason,
            "timestamp": str(int(time.time() * 1000)),
        }
        # Copy original fields
        for k, v in fields.items():
            key_str = k.decode() if isinstance(k, bytes) else k
            val_str = v.decode() if isinstance(v, bytes) else str(v)
            dlq_entry[f"orig_{key_str}"] = val_str

        await self._redis.xadd(dlq_key, dlq_entry)  # type: ignore
        logger.warning(
            "Message moved to DLQ: stream=%s, msg_id=%s, reason=%s",
            stream_name, msg_id, reason,
        )

    # ==================================================================
    # Data Plane (Redis Pub/Sub) — best effort, may lose messages
    # ==================================================================

    async def publish_data(
        self,
        channel: str,
        data: dict[str, Any],
    ) -> int:
        """Publish a data-plane notification via Pub/Sub.

        Returns: Number of subscribers that received the message.
        """
        key = f"{_PUBSUB_PREFIX}{channel}"
        payload = json.dumps(data, ensure_ascii=False)
        count = await self._redis.publish(key, payload)
        logger.debug("Data message published: channel=%s, receivers=%d", channel, count)
        return count

    async def subscribe_data(
        self,
        channel: str,
        handler: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> None:
        """Subscribe to data-plane notifications."""
        key = f"{_PUBSUB_PREFIX}{channel}"
        await self._pubsub.subscribe(key)

        self._running = True
        while self._running:
            try:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True, timeout=1.0
                )
                if message and message["type"] == "message":
                    data_raw = message["data"]
                    if isinstance(data_raw, bytes):
                        data_raw = data_raw.decode()
                    data = json.loads(data_raw)
                    await handler(data)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Pub/Sub error on channel %s: %s", channel, e)
                await asyncio.sleep(0.5)

    # ==================================================================
    # Lifecycle
    # ==================================================================

    def stop(self) -> None:
        """Signal the consumer/subscriber loops to stop."""
        self._running = False

    async def close(self) -> None:
        """Clean up resources."""
        self.stop()
        await self._pubsub.close()
