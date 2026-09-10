"""
Survey listing/read endpoints.
"""

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Header, Query

from core.account_identity import account_cache_id
from core.config import LS_SURVEYS_TIMEOUT_SECONDS
from core.security import AuthenticatedIdentity, verify_token
from schemas import SurveysResp
from services.error_mapper import raise_limesurvey_error
from repositories.cache_repository import cache_repository
from services.limesurvey_session_service import resume_limesurvey_client
from services.remote_call_executor import run_remote_call


router = APIRouter(tags=["surveys"])


def _survey_list_cache_key(api: Any) -> str:
    """Identify one account without embedding its remote key in the Redis key."""
    return f"ls:surveys:{account_cache_id(api)}"


@router.get("/surveys", response_model=SurveysResp)
async def list_surveys(
    session_key: str = Header(..., alias="X-LimeSurvey-Session"),
    refresh: bool = Query(
        False,
        description="Bypass the short-lived survey-list cache and read LimeSurvey again.",
    ),
    auth: AuthenticatedIdentity = Depends(verify_token),
) -> SurveysResp:
    """
    List available surveys for an active LS session.
    """
    api = await resume_limesurvey_client(session_key, auth)

    try:
        cache_key = _survey_list_cache_key(api)
        cached = None if refresh else await cache_repository.get_json(cache_key)
        if isinstance(cached, list):
            return cached

        surveys = await asyncio.wait_for(
            run_remote_call(api, api.survey.list_surveys),
            timeout=LS_SURVEYS_TIMEOUT_SECONDS,
        )

        await cache_repository.set_json(cache_key, surveys, 300)

        return surveys
    except (TimeoutError, asyncio.TimeoutError):
        await raise_limesurvey_error(
            session_key,
            Exception(f"list_surveys timed out after {int(LS_SURVEYS_TIMEOUT_SECONDS)}s"),
            "listing surveys",
        )
    except Exception as exc:
        await raise_limesurvey_error(session_key, exc, "listing surveys")
