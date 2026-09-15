"""
Health/status endpoints.
"""

import asyncio
from typing import Any, Dict

from fastapi import APIRouter, HTTPException

from core.config import APP_NAME, ENV, IS_PRODUCTION, ALLOW_IN_MEMORY_STATE
from schemas import DetailResp
from infrastructure.redis_client import get_redis_client


router = APIRouter(tags=["health"])


@router.get("/health", response_model=DetailResp)
async def health() -> DetailResp:
    """Report readiness, including the required session store, without credentials."""
    redis = get_redis_client()
    if redis is None:
        if IS_PRODUCTION or not ALLOW_IN_MEMORY_STATE:
            raise HTTPException(status_code=503, detail="Session store is unavailable")
    else:
        try:
            await asyncio.wait_for(redis.ping(), timeout=2)
        except Exception:
            raise HTTPException(status_code=503, detail="Session store is unavailable") from None
    return DetailResp(detail="ok")


@router.get("/smoke", response_model=Dict[str, Any])
def smoke() -> Dict[str, Any]:
    return {
        "app": APP_NAME,
        "env": ENV,
        "redis": bool(get_redis_client()),
        "remote_transport": "citric-requests",
    }
