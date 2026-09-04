"""
Health/status endpoints.
"""

from typing import Any, Dict

from fastapi import APIRouter

from core.config import APP_NAME, ENV
from schemas import DetailResp
from infrastructure.redis_client import get_redis_client


router = APIRouter(tags=["health"])


@router.get("/health", response_model=DetailResp)
def health() -> DetailResp:
    return DetailResp(detail="ok")


@router.get("/smoke", response_model=Dict[str, Any])
def smoke() -> Dict[str, Any]:
    return {
        "app": APP_NAME,
        "env": ENV,
        "redis": bool(get_redis_client()),
        "remote_transport": "citric-requests",
    }
