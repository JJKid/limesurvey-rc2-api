"""Rate limits must not become independent per worker during a Redis outage."""

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from repositories.cache_repository import CacheRepository
from services import login_rate_limiter, response_export_rate_limiter


@pytest.fixture(params=[login_rate_limiter, response_export_rate_limiter])
def limiter(request, monkeypatch):
    module = request.param
    monkeypatch.setattr(module, "_memory_attempts", {})
    if module is login_rate_limiter:
        monkeypatch.setattr(module, "LS_LOGIN_RATE_LIMIT_PER_MIN", 1)
        return module, lambda: module.enforce_login_rate_limit("test-client", "test-user")
    monkeypatch.setattr(module, "LS_RESPONSES_RATE_LIMIT_PER_MIN", 1)
    return module, lambda: module.enforce_response_export_rate_limit("test-session", 1)


@pytest.mark.parametrize("production,allow_memory", [(True, False), (True, True), (False, False)])
@pytest.mark.parametrize("outage", [False, True])
def test_redis_unavailability_fails_closed(limiter, monkeypatch, production, allow_memory, outage):
    module, call = limiter
    monkeypatch.setattr(module, "IS_PRODUCTION", production, raising=False)
    monkeypatch.setattr(module, "ALLOW_IN_MEMORY_STATE", allow_memory, raising=False)
    increment = AsyncMock(side_effect=ConnectionError("synthetic outage")) if outage else AsyncMock(return_value=None)
    monkeypatch.setattr(module.cache_repository, "increment_with_ttl", increment)
    with pytest.raises(HTTPException) as caught:
        asyncio.run(call())
    assert caught.value.status_code == 503
    assert module._memory_attempts == {}


def test_explicit_development_fallback_still_enforces_its_limit(limiter, monkeypatch):
    module, call = limiter
    monkeypatch.setattr(module, "IS_PRODUCTION", False, raising=False)
    monkeypatch.setattr(module, "ALLOW_IN_MEMORY_STATE", True, raising=False)
    monkeypatch.setattr(module.cache_repository, "increment_with_ttl", AsyncMock(return_value=None))
    asyncio.run(call())
    with pytest.raises(HTTPException) as caught:
        asyncio.run(call())
    assert caught.value.status_code == 429


def test_shared_limit_is_honored_without_creating_local_buckets(limiter, monkeypatch):
    module, call = limiter
    monkeypatch.setattr(module, "IS_PRODUCTION", True, raising=False)
    monkeypatch.setattr(module.cache_repository, "increment_with_ttl", AsyncMock(side_effect=[1, 2]))
    asyncio.run(call())
    with pytest.raises(HTTPException) as caught:
        asyncio.run(call())
    assert caught.value.status_code == 429
    assert module._memory_attempts == {}


def test_counter_and_expiration_use_one_atomic_redis_operation(monkeypatch):
    client = AsyncMock()
    client.eval.return_value = 1
    monkeypatch.setattr("repositories.cache_repository.get_redis_client", lambda: client)
    assert asyncio.run(CacheRepository().increment_with_ttl("test-counter", 60)) == 1
    client.eval.assert_awaited_once()
    script, number_of_keys, key, ttl = client.eval.call_args.args
    assert number_of_keys == 1 and key == "test-counter" and ttl == 60
    assert "INCR" in script and "EXPIRE" in script and "'NX'" in script
    client.incr.assert_not_awaited()
    client.expire.assert_not_awaited()
