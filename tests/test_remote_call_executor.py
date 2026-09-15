import asyncio
from types import SimpleNamespace

import pytest

from repositories import concurrency_repository
from services.remote_call_executor import run_remote_call


def test_cancelled_caller_keeps_slot_until_worker_finishes(monkeypatch):
    monkeypatch.setattr(concurrency_repository, "get_redis_client", lambda: None)
    monkeypatch.setattr(concurrency_repository, "LS_ACCOUNT_MAX_CONCURRENT_CALLS", 1)
    concurrency_repository._process_semaphores.clear()
    api = SimpleNamespace(url="https://example.test/remotecontrol", username="test")

    async def run():
        loop = asyncio.get_running_loop()
        entered = asyncio.Event()
        release = asyncio.Event()
        second_entered = asyncio.Event()

        def first_operation():
            loop.call_soon_threadsafe(entered.set)
            asyncio.run_coroutine_threadsafe(release.wait(), loop).result(timeout=2)

        def second_operation():
            loop.call_soon_threadsafe(second_entered.set)

        first = asyncio.create_task(run_remote_call(api, first_operation))
        try:
            await asyncio.wait_for(entered.wait(), 1)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            second = asyncio.create_task(run_remote_call(api, second_operation))
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(second_entered.wait(), 0.03)
            release.set()
            await asyncio.wait_for(second, 1)
            assert second_entered.is_set()
        finally:
            release.set()

    asyncio.run(run())


def test_cancelled_queued_call_never_reaches_limesurvey(monkeypatch):
    monkeypatch.setattr(concurrency_repository, "get_redis_client", lambda: None)
    monkeypatch.setattr(concurrency_repository, "LS_ACCOUNT_MAX_CONCURRENT_CALLS", 1)
    concurrency_repository._process_semaphores.clear()
    api = SimpleNamespace(url="https://example.test/remotecontrol", username="test")
    called = []

    async def run():
        from core.account_identity import account_cache_id
        async with concurrency_repository.account_concurrency_slot(account_cache_id(api)):
            queued = asyncio.create_task(run_remote_call(api, lambda: called.append(True)))
            await asyncio.sleep(0)
            queued.cancel()
            with pytest.raises(asyncio.CancelledError):
                await queued
        await asyncio.sleep(0)
        assert called == []

    asyncio.run(run())
