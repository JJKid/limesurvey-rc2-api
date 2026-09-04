import asyncio

import repositories.concurrency_repository as concurrency_repository


def test_development_fallback_limits_separate_requests_for_one_account(monkeypatch):
    monkeypatch.setattr(concurrency_repository, "get_redis_client", lambda: None)
    monkeypatch.setattr(concurrency_repository, "LS_ACCOUNT_MAX_CONCURRENT_CALLS", 1)
    concurrency_repository._process_semaphores.clear()
    active = 0
    maximum = 0

    async def operation():
        nonlocal active, maximum
        async with concurrency_repository.account_concurrency_slot("same-account"):
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1

    async def run():
        await asyncio.gather(operation(), operation(), operation())

    asyncio.run(run())
    assert maximum == 1
