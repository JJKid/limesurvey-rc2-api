"""Run synchronous Citric calls without blocking FastAPI's event loop."""

from __future__ import annotations

import asyncio
from functools import partial
from typing import Any, Callable, TypeVar

from core.account_identity import account_cache_id
from repositories.concurrency_repository import account_concurrency_slot


T = TypeVar("T")


async def run_remote_call(
    api: Any,
    operation: Callable[..., T],
    *args: Any,
    **kwargs: Any,
) -> T:
    """Execute one Citric operation under the shared per-account limit."""
    async with account_concurrency_slot(account_cache_id(api)):
        return await asyncio.to_thread(partial(operation, *args, **kwargs))
