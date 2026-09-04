"""Load complete LimeSurvey question data with bounded remote work and caching.

This module owns the orchestration needed to turn one survey id into the raw,
enriched question rows consumed by the SurveyStructure builder. HTTP concerns
such as headers, JWT validation and status codes remain in the routers.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional

from core.account_identity import account_cache_id
from core.config import DEFAULT_OPTIMAL_PARAMS
from repositories.cache_repository import cache_repository
from schemas import QuestionsResp
from services.error_mapper import is_limesurvey_remote_unreachable
from services.limesurvey_fetchers import make_fetchers
from services.optimizer_service import get_cached_optimal_params
from services.remote_call_executor import run_remote_call


logger = logging.getLogger("uvicorn.error")
QUESTIONS_CACHE_TTL_SECONDS = 600


class SurveyGroupsNotFoundError(LookupError):
    """The requested survey does not contain question groups."""


def build_grouped_questions_cache_key(
    api: Any,
    sid: int,
    language: Optional[str] = None,
) -> str:
    """Return a cache key scoped to one LimeSurvey account and survey.

    Survey ids are only unique inside one LimeSurvey installation. The URL and
    username therefore participate in a SHA-256 digest, but neither they nor
    the remote session key are exposed in the Redis key.
    """
    account_hash = account_cache_id(api)
    language_key = (language or "auto").strip().lower()
    return f"survey:questions:groups:props:{account_hash}:{sid}:{language_key}"


async def load_questions(
    api: Any,
    sid: int,
    language: Optional[str] = None,
    survey_groups: Optional[QuestionsResp] = None,
    refresh: bool = False,
) -> QuestionsResp:
    """Load and enrich all questions for one LimeSurvey survey.

    Reuse a short-lived account/language-specific cache when available. On a
    cache miss, read the optimizer parameters, bound concurrent remote calls
    with a semaphore, retry temporary network failures, merge group relevance
    with question data and cache the completed result.
    """
    cache_key = build_grouped_questions_cache_key(api, sid, language)
    cached_questions = None if refresh else cache_repository.get_json(cache_key)
    if isinstance(cached_questions, list):
        logger.info(
            "grouped_questions cache hit sid=%s cache_key=%s questions=%s",
            sid,
            cache_key,
            len(cached_questions),
        )
        return cached_questions

    params = get_cached_optimal_params(api) or DEFAULT_OPTIMAL_PARAMS
    semaphore = asyncio.Semaphore(params["semaphore"])
    max_attempts = params["maxAttempts"]

    logger.info("grouped_questions cache miss sid=%s cache_key=%s", sid, cache_key)
    if survey_groups is None:
        survey_groups = await run_remote_call(api, api.survey.list_groups, sid, language)
    if not survey_groups:
        raise SurveyGroupsNotFoundError(f"No groups found for survey ID {sid}")

    logger.info(
        "grouped_questions loading sid=%s groups=%s semaphore=%s max_attempts=%s",
        sid,
        len(survey_groups),
        params["semaphore"],
        max_attempts,
    )
    fetch_questions, fetch_properties = make_fetchers(api)
    group_results = await asyncio.gather(*(
        _load_group_questions(
            sid=sid,
            group=group,
            semaphore=semaphore,
            max_attempts=max_attempts,
            fetch_questions=fetch_questions,
            fetch_properties=fetch_properties,
            language=language,
        )
        for group in survey_groups
    ))
    questions = [question for group_result in group_results for question in group_result]
    logger.info("grouped_questions loaded sid=%s questions=%s", sid, len(questions))

    cache_repository.set_json(cache_key, questions, QUESTIONS_CACHE_TTL_SECONDS)
    if questions:
        logger.info(
            "grouped_questions cache set sid=%s cache_key=%s ttl_seconds=%s",
            sid,
            cache_key,
            QUESTIONS_CACHE_TTL_SECONDS,
        )

    return questions


async def _load_group_questions(
    sid: int,
    group: Dict[str, Any],
    semaphore: asyncio.Semaphore,
    max_attempts: int,
    fetch_questions,
    fetch_properties,
    language: Optional[str] = None,
) -> QuestionsResp:
    """Load one group's questions and enrich each one with its properties.

    A non-connectivity failure in one property request skips only that question.
    A connectivity failure aborts the complete load so the router can report the
    remote LimeSurvey instance as unavailable.
    """
    group_id = group["gid"]
    group_relevance = str(group.get("grelevance") or "1").strip() or "1"

    logger.info("group_processing start sid=%s gid=%s", sid, group_id)
    group_questions = await fetch_questions(
        sid,
        group_id,
        semaphore,
        max_attempts,
        language,
    )
    logger.info(
        "group_processing fetched questions sid=%s gid=%s count=%s",
        sid,
        group_id,
        len(group_questions),
    )
    if not group_questions:
        logger.warning("group_processing empty group sid=%s gid=%s", sid, group_id)
        return []

    tasks = [
        fetch_properties(question["qid"], semaphore, max_attempts, language)
        for question in group_questions
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    enriched_questions: QuestionsResp = []
    for question, result in zip(group_questions, results):
        if isinstance(result, Exception):
            if is_limesurvey_remote_unreachable(result):
                raise result
            logger.warning(
                "group_processing question property fetch failed sid=%s gid=%s qid=%s error=%s",
                sid,
                group_id,
                question["qid"],
                result,
            )
            continue

        enriched_questions.append({
            **question,
            **result,
            "grelevance": group_relevance,
            "full_condition": (
                f"({group_relevance}) AND ({result.get('condition', '1')})"
            ),
        })

    logger.info(
        "group_processing done sid=%s gid=%s enriched_questions=%s skipped_questions=%s",
        sid,
        group_id,
        len(enriched_questions),
        len(group_questions) - len(enriched_questions),
    )
    return enriched_questions
