"""Cross-request concurrency slots scoped to one LimeSurvey account."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import time
import uuid
from typing import AsyncIterator, Dict

from core.config import (
    LS_ACCOUNT_CONCURRENCY_LEASE_SECONDS,
    LS_ACCOUNT_CONCURRENCY_WAIT_SECONDS,
    LS_ACCOUNT_MAX_CONCURRENT_CALLS,
)
from infrastructure.redis_client import get_redis_client


_ACQUIRE_SCRIPT = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local expires = tonumber(ARGV[2])
local token = ARGV[3]
local limit = tonumber(ARGV[4])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZCARD', key) < limit then
  redis.call('ZADD', key, expires, token)
  redis.call('EXPIRE', key, math.ceil(expires - now))
  return 1
end
return 0
"""


_process_semaphores: Dict[str, asyncio.Semaphore] = {}


@asynccontextmanager
async def account_concurrency_slot(account_id: str) -> AsyncIterator[None]:
    """Limit concurrent RC2 calls across requests and, with Redis, workers."""
    client = get_redis_client()
    if client is None:
        semaphore = _process_semaphores.setdefault(
            account_id,
            asyncio.Semaphore(max(1, LS_ACCOUNT_MAX_CONCURRENT_CALLS)),
        )
        async with semaphore:
            yield
        return

    key = f"ls:concurrency:{account_id}"
    token = uuid.uuid4().hex
    deadline = time.monotonic() + LS_ACCOUNT_CONCURRENCY_WAIT_SECONDS
    while True:
        now = time.time()
        acquired = await asyncio.to_thread(
            client.eval,
            _ACQUIRE_SCRIPT,
            1,
            key,
            now,
            now + LS_ACCOUNT_CONCURRENCY_LEASE_SECONDS,
            token,
            max(1, LS_ACCOUNT_MAX_CONCURRENT_CALLS),
        )
        if acquired:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError("Timed out waiting for a LimeSurvey account concurrency slot")
        await asyncio.sleep(0.05)

    try:
        yield
    finally:
        await asyncio.to_thread(client.zrem, key, token)
