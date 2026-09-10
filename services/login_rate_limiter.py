"""
Basic rate limiter for /login-limesurvey.

Uses Redis when available, with in-memory fallback.
"""

import time
from collections import deque
from typing import Deque, Dict

from fastapi import HTTPException

from core.config import LS_LOGIN_RATE_LIMIT_PER_MIN
from repositories.cache_repository import cache_repository


_memory_attempts: Dict[str, Deque[float]] = {}


async def enforce_login_rate_limit(client_ip: str, username: str) -> None:
    limit = max(1, int(LS_LOGIN_RATE_LIMIT_PER_MIN))
    key = _build_key(client_ip, username)

    redis_key = f"ls:rate:login:{key}"
    try:
        current = await cache_repository.increment_with_ttl(redis_key, 60)
        if current is not None:
            if current > limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"Too many login attempts. Try again in 60 seconds (limit: {limit}/min).",
                )
            return
    except HTTPException:
        raise
    except Exception:
        # Development fallback when Redis becomes unavailable.
        pass

    now = time.time()
    bucket = _memory_attempts.setdefault(key, deque())
    _drop_expired(bucket, now)
    if len(bucket) >= limit:
        raise HTTPException(
            status_code=429,
            detail=f"Too many login attempts. Try again in 60 seconds (limit: {limit}/min).",
        )
    bucket.append(now)


def _build_key(client_ip: str, username: str) -> str:
    normalized_ip = (client_ip or 'unknown').strip().lower()
    normalized_username = (username or 'unknown').strip().lower()
    return f"{normalized_ip}::{normalized_username}"


def _drop_expired(bucket: Deque[float], now: float) -> None:
    while bucket and (now - bucket[0]) > 60:
        bucket.popleft()
