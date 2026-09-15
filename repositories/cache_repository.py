"""Small JSON/text cache API over the shared Redis connection."""

import json
from typing import Any, Optional

from infrastructure.redis_client import get_redis_client


class CacheRepository:
    """Keep Redis serialization and key operations out of route handlers."""

    async def get_json(self, key: str) -> Optional[Any]:
        client = get_redis_client()
        if client is None:
            return None
        value = await client.get(key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return None

    async def set_json(self, key: str, value: Any, ttl_seconds: int) -> None:
        client = get_redis_client()
        if client is not None:
            await client.set(key, json.dumps(value), ex=ttl_seconds)

    async def get_text(self, key: str) -> Optional[str]:
        client = get_redis_client()
        if client is None:
            return None
        value = await client.get(key)
        return None if value is None else str(value)

    async def set_text(self, key: str, value: object, ttl_seconds: Optional[int] = None) -> None:
        client = get_redis_client()
        if client is not None:
            await client.set(key, value, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        client = get_redis_client()
        if client is not None:
            await client.delete(key)

    async def increment_with_ttl(self, key: str, ttl_seconds: int) -> Optional[int]:
        """Increment and set expiry atomically, repairing a counter with no TTL."""
        client = get_redis_client()
        if client is None:
            return None
        return int(await client.eval("""
            local current = redis.call('INCR', KEYS[1])
            redis.call('EXPIRE', KEYS[1], ARGV[1], 'NX')
            return current
        """, 1, key, ttl_seconds))

    async def acquire_lock(self, key: str, ttl_seconds: int) -> bool:
        client = get_redis_client()
        return bool(client and await client.set(key, "1", nx=True, ex=ttl_seconds))

    async def add_expiration(self, key: str, member: str, expires_at: float) -> None:
        client = get_redis_client()
        if client is not None:
            await client.zadd(key, {member: expires_at})

    async def remove_expiration(self, key: str, member: str) -> None:
        client = get_redis_client()
        if client is not None:
            await client.zrem(key, member)

    async def take_expired_members(self, key: str, now: float) -> list[str]:
        """Claim due members so only one worker performs their cleanup."""
        client = get_redis_client()
        if client is None:
            return []
        candidates = await client.zrangebyscore(key, 0, now)
        claimed = []
        for member in candidates:
            if await client.zrem(key, member):
                claimed.append(str(member))
        return claimed


cache_repository = CacheRepository()
