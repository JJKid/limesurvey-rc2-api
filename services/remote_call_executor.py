"""Run synchronous Citric calls without blocking FastAPI's event loop."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any, Callable, TypeVar

from core.account_identity import account_cache_id
from repositories.concurrency_repository import account_concurrency_slot


T = TypeVar("T")
_running_calls: set[asyncio.Task] = set()


def _discard_completed_call(task: asyncio.Task) -> None:
    """Retain cancelled callers' work until its thread and concurrency slot finish."""
    _running_calls.discard(task)
    if not task.cancelled():
        # The caller may have timed out; retrieve the result's exception as well.
        task.exception()


async def run_remote_call(
    api: Any,
    operation: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    """Keep the account slot until HTTP finishes, even if the caller times out.

    Cancelling ``to_thread`` cannot stop requests in its worker thread. Shield
    the operation and slot together so a cancelled HTTP request does not free
    capacity while LimeSurvey is still processing its remote call.
    """
    started = False

    async def execute() -> T:
        nonlocal started
        async with account_concurrency_slot(account_cache_id(api)):
            started = True
            return await asyncio.to_thread(partial(operation, *args, **kwargs))

    task = asyncio.create_task(execute())
    _running_calls.add(task)
    task.add_done_callback(_discard_completed_call)
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        if not started:
            # A request cancelled while queued must not call LimeSurvey later.
            task.cancel()
        raise
