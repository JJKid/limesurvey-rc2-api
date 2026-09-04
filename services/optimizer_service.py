"""
Optimizer cache orchestration per LimeSurvey account.

Why account-level cache?
- A user can open many local sessions against same LS URL/username.
- We compute optimal params once and reuse.
"""

import logging
import time
from typing import Dict, Optional

from core.account_identity import account_cache_id
from services.limesurvey_client import LimeSurveyClient

from core.config import DEFAULT_OPTIMAL_PARAMS
from services.hybrid_optimizer import HybridOptimizer
from services.limesurvey_fetchers import make_fetchers
from repositories.cache_repository import cache_repository


logger = logging.getLogger(__name__)


def generate_account_cache_id(api: LimeSurveyClient) -> str:
    """
    Stable cache key ID per account: sha256(url|username).
    """
    return account_cache_id(api)


def generate_optimizer_redis_keys(account_cache_id: str) -> Dict[str, str]:
    """
    Return all Redis keys used by optimizer cache for one account.
    """
    prefix = f"opt:{account_cache_id}"
    return {
        "semaphore": f"{prefix}:semaphore",
        "maxAttempts": f"{prefix}:max-attempts",
        "score": f"{prefix}:score",
        "timestamp": f"{prefix}:timestamp",
        "lock": f"{prefix}:lock",
    }


def get_cached_optimal_params(api: LimeSurveyClient) -> Optional[Dict[str, int]]:
    """
    Read cached optimizer params from Redis, if available.
    """
    account_id = generate_account_cache_id(api)
    keys = generate_optimizer_redis_keys(account_id)
    semaphore_value = cache_repository.get_text(keys["semaphore"])
    max_attempts_value = cache_repository.get_text(keys["maxAttempts"])

    if semaphore_value and max_attempts_value:
        try:
            return {
                "semaphore": int(semaphore_value),
                "maxAttempts": int(max_attempts_value),
            }
        except Exception:
            return None
    return None


async def optimize_user_account_params(api: LimeSurveyClient) -> None:
    """
    Compute and persist optimal concurrency/retry params for one account.
    """
    account_id = generate_account_cache_id(api)
    keys = generate_optimizer_redis_keys(account_id)

    if get_cached_optimal_params(api):
        return

    # Avoid parallel optimizer runs for same account.
    got_lock = cache_repository.acquire_lock(keys["lock"], 900)
    if not got_lock:
        return

    try:
        fetch_questions_fn, fetch_properties_fn = make_fetchers(api)
        optimizer = HybridOptimizer(
            api=api,
            fetch_questions_fn=fetch_questions_fn,
            fetch_properties_fn=fetch_properties_fn,
        )

        logger.info("Calculating LimeSurvey concurrency parameters")
        optimal_params = await optimizer.find_optimal_parameters()
        logger.info("Calculated LimeSurvey concurrency parameters: %s", optimal_params)

        semaphore_value = int(optimal_params.get("semaphore", DEFAULT_OPTIMAL_PARAMS["semaphore"]))
        max_attempts_value = int(
            optimal_params.get("maxAttempts", DEFAULT_OPTIMAL_PARAMS["maxAttempts"])
        )
        score_value = float(optimal_params.get("score", 0.0))
        timestamp_value = int(time.time())

        cache_repository.set_text(keys["semaphore"], semaphore_value)
        cache_repository.set_text(keys["maxAttempts"], max_attempts_value)
        cache_repository.set_text(keys["score"], score_value)
        cache_repository.set_text(keys["timestamp"], timestamp_value)
    finally:
        cache_repository.delete(keys["lock"])
