"""
Idempotency Engine
==================
Prevents duplicate processing of WhatsApp webhook messages using
a Redis-backed HashSet (DuplicateMessageSet).

Lookup complexity: O(1)
TTL: 24 hours (configurable)
"""

import logging
from redis.asyncio import Redis

logger = logging.getLogger(__name__)

IDEMPOTENCY_KEY_PREFIX = "idempotency:msg:"


class IdempotencyService:
    """
    Redis-backed idempotency check using SET NX (set if not exists).
    Thread-safe and horizontally scalable.
    """

    def __init__(self, redis: Redis, ttl_seconds: int = 86400) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    async def is_duplicate(self, message_id: str) -> bool:
        """
        Check if a message_id has already been processed.
        Returns True if it is a duplicate (already seen).
        Returns False if this is the first time we see this message_id,
        and atomically marks it as processed.

        Uses Redis SET NX EX for atomic check-and-set (O(1)).
        """
        key = f"{IDEMPOTENCY_KEY_PREFIX}{message_id}"
        # SET key value NX EX ttl
        # Returns True if the key was set (first time), None if already exists
        was_set = await self._redis.set(key, "1", nx=True, ex=self._ttl)
        is_dup = was_set is None
        if is_dup:
            logger.info("Duplicate message detected: %s", message_id)
        return is_dup

    async def mark_processed(self, message_id: str) -> None:
        """
        Explicitly mark a message as processed (useful for pre-seeding).
        """
        key = f"{IDEMPOTENCY_KEY_PREFIX}{message_id}"
        await self._redis.set(key, "1", ex=self._ttl)

    async def remove(self, message_id: str) -> None:
        """Remove idempotency record (useful for testing/retries)."""
        key = f"{IDEMPOTENCY_KEY_PREFIX}{message_id}"
        await self._redis.delete(key)
