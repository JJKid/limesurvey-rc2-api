from unittest.mock import AsyncMock
import asyncio

import pytest
from fastapi import HTTPException
from routers import health as routes


def test_production_requires_redis(monkeypatch):
    monkeypatch.setattr(routes, "IS_PRODUCTION", True)
    monkeypatch.setattr(routes, "get_redis_client", lambda: None)
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes.health())
    assert error.value.status_code == 503


@pytest.mark.parametrize("available", [True, False])
def test_readiness_checks_session_store(monkeypatch, available):
    redis = AsyncMock()
    if not available:
        redis.ping.side_effect = ConnectionError("private internal connection details")
    monkeypatch.setattr(routes, "get_redis_client", lambda: redis)
    if available:
        assert asyncio.run(routes.health()).detail == "ok"
    else:
        with pytest.raises(HTTPException) as error:
            asyncio.run(routes.health())
        assert error.value.status_code == 503
        assert error.value.detail == "Session store is unavailable"
    redis.ping.assert_awaited_once()
