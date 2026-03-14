"""
Tests for webhook idempotency service.
Duplicate messages must be detected and rejected.
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.idempotency import IdempotencyService


class TestIdempotencyService:
    @pytest.mark.asyncio
    async def test_first_message_not_duplicate(self):
        """First time we see a message ID should not be a duplicate."""
        redis = AsyncMock()
        redis.set.return_value = True  # SET NX succeeded (new key)

        svc = IdempotencyService(redis, ttl_seconds=86400)
        is_dup = await svc.is_duplicate("msg-001")

        assert is_dup is False
        redis.set.assert_called_once_with(
            "idempotency:msg:msg-001", "1", nx=True, ex=86400
        )

    @pytest.mark.asyncio
    async def test_second_message_is_duplicate(self):
        """Second time we see the same message ID should be a duplicate."""
        redis = AsyncMock()
        redis.set.return_value = None  # SET NX failed (key already exists)

        svc = IdempotencyService(redis, ttl_seconds=86400)
        is_dup = await svc.is_duplicate("msg-001")

        assert is_dup is True

    @pytest.mark.asyncio
    async def test_different_messages_not_duplicate(self):
        """Different message IDs should each be treated as new."""
        redis = AsyncMock()
        redis.set.return_value = True  # Always succeeds (new key)

        svc = IdempotencyService(redis)
        assert await svc.is_duplicate("msg-001") is False
        assert await svc.is_duplicate("msg-002") is False
        assert await svc.is_duplicate("msg-003") is False

    @pytest.mark.asyncio
    async def test_mark_processed(self):
        """mark_processed should set the key without NX constraint."""
        redis = AsyncMock()

        svc = IdempotencyService(redis, ttl_seconds=3600)
        await svc.mark_processed("msg-999")

        redis.set.assert_called_once_with(
            "idempotency:msg:msg-999", "1", ex=3600
        )

    @pytest.mark.asyncio
    async def test_remove(self):
        """remove should delete the idempotency key."""
        redis = AsyncMock()

        svc = IdempotencyService(redis)
        await svc.remove("msg-001")

        redis.delete.assert_called_once_with("idempotency:msg:msg-001")

    @pytest.mark.asyncio
    async def test_key_includes_tenant_prefix(self):
        """Keys should be namespaced with the idempotency prefix."""
        redis = AsyncMock()
        redis.set.return_value = True

        svc = IdempotencyService(redis)
        await svc.is_duplicate("tenant-A:msg-100")

        call_args = redis.set.call_args[0]
        assert call_args[0].startswith("idempotency:msg:")

    @pytest.mark.asyncio
    async def test_ttl_is_applied(self):
        """Redis SET should be called with the configured TTL."""
        redis = AsyncMock()
        redis.set.return_value = True

        custom_ttl = 3600
        svc = IdempotencyService(redis, ttl_seconds=custom_ttl)
        await svc.is_duplicate("msg-ttl-test")

        _, kwargs = redis.set.call_args
        assert kwargs["ex"] == custom_ttl
