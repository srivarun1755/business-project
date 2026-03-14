"""
Redis connection and caching utilities.
Provides O(1) lookups for frequently accessed data.
"""
from typing import Any, Optional
import json
import redis.asyncio as redis
from src.core.config import settings


class RedisCache:
    """Redis cache manager for O(1) data lookups."""
    
    def __init__(self):
        self._pool: Optional[redis.ConnectionPool] = None
        self._client: Optional[redis.Redis] = None
    
    async def connect(self) -> None:
        """Initialize Redis connection pool."""
        self._pool = redis.ConnectionPool.from_url(
            settings.redis_url,
            decode_responses=True,
            max_connections=20,
        )
        self._client = redis.Redis(connection_pool=self._pool)
    
    async def disconnect(self) -> None:
        """Close Redis connections."""
        if self._client:
            await self._client.close()
        if self._pool:
            await self._pool.disconnect()
    
    @property
    def client(self) -> redis.Redis:
        """Get Redis client."""
        if not self._client:
            raise RuntimeError("Redis not connected. Call connect() first.")
        return self._client
    
    # Key prefixes for different data types
    PRODUCT_ALIAS_PREFIX = "product:alias:"
    CUSTOMER_PREFIX = "customer:"
    IDEMPOTENCY_PREFIX = "idempotent:"
    ORDER_PREFIX = "order:"
    
    # --- Product Alias Cache (O(1) lookups) ---
    
    async def set_product_alias(
        self, 
        alias: str, 
        canonical_product_id: str,
        ttl: int = 86400  # 24 hours
    ) -> None:
        """Cache a product alias to canonical ID mapping."""
        key = f"{self.PRODUCT_ALIAS_PREFIX}{alias.lower()}"
        await self.client.setex(key, ttl, canonical_product_id)
    
    async def get_product_alias(self, alias: str) -> Optional[str]:
        """Get canonical product ID from alias. O(1) operation."""
        key = f"{self.PRODUCT_ALIAS_PREFIX}{alias.lower()}"
        return await self.client.get(key)
    
    async def bulk_set_product_aliases(
        self, 
        aliases: dict[str, str],
        ttl: int = 86400
    ) -> None:
        """Bulk set product aliases using pipeline."""
        async with self.client.pipeline(transaction=True) as pipe:
            for alias, product_id in aliases.items():
                key = f"{self.PRODUCT_ALIAS_PREFIX}{alias.lower()}"
                pipe.setex(key, ttl, product_id)
            await pipe.execute()
    
    # --- Idempotency Key Management ---
    
    async def check_idempotency(
        self, 
        key: str, 
        ttl: int = 3600  # 1 hour
    ) -> bool:
        """
        Check if an idempotency key exists.
        Returns True if key is new (first time), False if duplicate.
        Uses SETNX for atomic check-and-set.
        """
        full_key = f"{self.IDEMPOTENCY_PREFIX}{key}"
        result = await self.client.setnx(full_key, "1")
        if result:
            await self.client.expire(full_key, ttl)
        return bool(result)
    
    async def get_idempotent_result(self, key: str) -> Optional[dict]:
        """Get cached result for idempotent operation."""
        full_key = f"{self.IDEMPOTENCY_PREFIX}{key}:result"
        result = await self.client.get(full_key)
        if result:
            return json.loads(result)
        return None
    
    async def set_idempotent_result(
        self, 
        key: str, 
        result: dict,
        ttl: int = 3600
    ) -> None:
        """Cache result for idempotent operation."""
        full_key = f"{self.IDEMPOTENCY_PREFIX}{key}:result"
        await self.client.setex(full_key, ttl, json.dumps(result))
    
    # --- Customer Cache ---
    
    async def cache_customer(
        self, 
        phone: str, 
        customer_data: dict,
        ttl: int = 3600
    ) -> None:
        """Cache customer data for quick lookups."""
        key = f"{self.CUSTOMER_PREFIX}{phone}"
        await self.client.setex(key, ttl, json.dumps(customer_data))
    
    async def get_cached_customer(self, phone: str) -> Optional[dict]:
        """Get cached customer data. O(1) operation."""
        key = f"{self.CUSTOMER_PREFIX}{phone}"
        result = await self.client.get(key)
        if result:
            return json.loads(result)
        return None
    
    async def invalidate_customer(self, phone: str) -> None:
        """Invalidate customer cache."""
        key = f"{self.CUSTOMER_PREFIX}{phone}"
        await self.client.delete(key)
    
    # --- Generic cache operations ---
    
    async def get(self, key: str) -> Optional[str]:
        """Generic get operation."""
        return await self.client.get(key)
    
    async def set(
        self, 
        key: str, 
        value: Any, 
        ttl: Optional[int] = None
    ) -> None:
        """Generic set operation."""
        if ttl:
            await self.client.setex(key, ttl, json.dumps(value))
        else:
            await self.client.set(key, json.dumps(value))
    
    async def delete(self, key: str) -> None:
        """Delete a key."""
        await self.client.delete(key)
    
    async def exists(self, key: str) -> bool:
        """Check if key exists."""
        return bool(await self.client.exists(key))


# Global cache instance
redis_cache = RedisCache()


async def get_redis_cache() -> RedisCache:
    """Dependency to get Redis cache instance."""
    return redis_cache
