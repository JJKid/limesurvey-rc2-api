"""Rate-limit LimeSurvey response exports without storing response content."""

import hashlib
import time
from collections import deque
from typing import Deque, Dict

from fastapi import HTTPException

from core.config import LS_RESPONSES_RATE_LIMIT_PER_MIN
from repositories.cache_repository import cache_repository


_memory_attempts: Dict[str, Deque[float]] = {}


async def enforce_response_export_rate_limit(session_key: str, survey_id: int) -> None:
    """Limit exports per local LimeSurvey session and survey."""
    limit = max(1, LS_RESPONSES_RATE_LIMIT_PER_MIN)
    identity = hashlib.sha256(f"{session_key}:{survey_id}".encode("utf-8")).hexdigest()

    redis_key = f"ls:rate:responses:{identity}"
    try:
        current = await cache_repository.increment_with_ttl(redis_key, 60)
        if current is not None:
            if current > limit:
                raise _rate_limit_error(limit)
            return
    except HTTPException:
        raise
    except Exception:
        pass

    now = time.time()
    bucket = _memory_attempts.setdefault(identity, deque())
    while bucket and now - bucket[0] > 60:
        bucket.popleft()
    if len(bucket) >= limit:
        raise _rate_limit_error(limit)
    bucket.append(now)


def _rate_limit_error(limit: int) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail={
            "code": "LS_RESPONSE_EXPORT_RATE_LIMITED",
            "message": f"Too many LimeSurvey response exports. Try again in 60 seconds (limit: {limit}/min).",
        },
    )
