"""Own the shared Redis connection used by this FastAPI process."""

import logging
from typing import Optional

import redis.asyncio as redis

from core.config import (
    ALLOW_IN_MEMORY_STATE,
    IS_PRODUCTION,
    REDIS_DB,
    REDIS_HOST,
    REDIS_PASSWORD,
    REDIS_PORT,
    REDIS_SSL,
)


logger = logging.getLogger(__name__)
_redis_client: Optional[redis.Redis] = None


async def initialize_redis() -> None:
    """Open and verify Redis, failing closed in production."""
    global _redis_client
    try:
        client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            db=REDIS_DB,
            ssl=REDIS_SSL,
            decode_responses=True,
        )
        await client.ping()
        _redis_client = client
        logger.info("Connected to Redis DB %s", REDIS_DB)
    except Exception as exc:
        _redis_client = None
        if IS_PRODUCTION or not ALLOW_IN_MEMORY_STATE:
            raise RuntimeError("Redis is required but could not be reached") from exc
        logger.warning("Redis is unavailable; development-only memory state is active: %s", exc)


async def close_redis() -> None:
    """Close the process Redis connection."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


def get_redis_client() -> Optional[redis.Redis]:
    """Return the initialized Redis client, or None in permitted development mode."""
    return _redis_client
