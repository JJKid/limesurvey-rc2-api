"""Concurrent LimeSurvey question fetches with bounded retry behavior."""

import asyncio
import random
from typing import Awaitable, Callable, Optional, TypeVar

import requests

from core.account_identity import account_cache_id
from core.config import (
    LS_REMOTE_BACKOFF_BASE_SECONDS,
    LS_REMOTE_BACKOFF_JITTER_RATIO,
    LS_REMOTE_BACKOFF_MAX_SECONDS,
)
from repositories.concurrency_repository import account_concurrency_slot
from services.limesurvey_client import LimeSurveyClient


T = TypeVar("T")


def make_fetchers(api: LimeSurveyClient):
    """Create two fetch functions bound to one LimeSurvey account and session.

    One function fetches the questions in a group. The other enriches one
    question with its properties. Both honor the supplied semaphore and retry
    only temporary network failures.
    """

    async def fetch_questions_by_group(
        survey_id, group_id, sem, max_attempts=3, language: Optional[str] = None
    ):
        """Fetch one group's questions with bounded concurrency.

        On a temporary LimeSurvey failure, wait with exponential backoff and
        retry. After the last attempt, propagate the final error to the layer
        that maps it to ``LS_UNREACHABLE``.
        """
        return await _call_with_retry(
            lambda: asyncio.to_thread(
                api.survey.list_questions,
                survey_id,
                group_id,
                language,
            ),
            sem,
            account_cache_id(api),
            max_attempts,
        )

    async def fetch_question_properties(
        qid, sem, max_attempts=3, language: Optional[str] = None
    ):
        """Fetch one question's properties with concurrency and retry limits.

        Properties enrich the basic question row with type, required state,
        conditions, options, subquestions, and other available data.
        """
        return await _call_with_retry(
            lambda: asyncio.to_thread(
                api.question.get_question_properties,
                qid,
                None,
                language,
            ),
            sem,
            account_cache_id(api),
            max_attempts,
        )

    return fetch_questions_by_group, fetch_question_properties


async def _call_with_retry(
    operation: Callable[[], Awaitable[T]],
    local_semaphore: asyncio.Semaphore,
    account_id: str,
    max_attempts: int,
) -> T:
    """Run one RC2 call with local/global limits and retry transient failures."""
    attempts = max(1, int(max_attempts))
    for attempt_index in range(attempts):
        try:
            async with local_semaphore:
                async with account_concurrency_slot(account_id):
                    return await operation()
        except (requests.Timeout, requests.ConnectionError):
            if attempt_index == attempts - 1:
                raise
            base_delay = min(
                LS_REMOTE_BACKOFF_MAX_SECONDS,
                LS_REMOTE_BACKOFF_BASE_SECONDS * (2 ** attempt_index),
            )
            jitter = random.uniform(0, base_delay * LS_REMOTE_BACKOFF_JITTER_RATIO)
            await asyncio.sleep(base_delay + jitter)
    raise RuntimeError("Unreachable retry state")
