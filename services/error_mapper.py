"""
Error mapping for LimeSurvey integration.

This module centralizes translation of low-level network/SDK failures into a
stable API contract consumed by the frontend.
"""

import asyncio
import re

from fastapi import HTTPException
import requests

from citric.exceptions import (
    InvalidJSONResponseError,
    LimeSurveyApiError,
    LimeSurveyStatusError,
    RPCInterfaceNotEnabledError,
)

from services.limesurvey_session_service import delete_limesurvey_session


def is_limesurvey_remote_unreachable(error: Exception) -> bool:
    """
    Classify connectivity failures towards remote LimeSurvey.
    """
    if isinstance(error, (
        TimeoutError,
        asyncio.TimeoutError,
        requests.Timeout,
        requests.ConnectionError,
    )):
        return True

    error_text = str(error).lower()
    unreachable_patterns = [
        "connection refused",
        "failed to establish a new connection",
        "max retries exceeded",
        "all connection attempts failed",
        "network is unreachable",
        "connection aborted",
        "name or service not known",
        "failed to resolve",
        "temporary failure in name resolution",
        "nodename nor servname provided",
        "read timed out",
        "connect timeout",
        "timed out",
    ]
    return any(pattern in error_text for pattern in unreachable_patterns)


async def raise_limesurvey_error(session_key: str, error: Exception, context: str) -> None:
    """
    Raise a normalized HTTPException with one of these codes:
      - LS_SESSION_EXPIRED (401)
      - LS_UNREACHABLE (503)
      - LS_REMOTE_CONTROL_UNAVAILABLE (502)
      - LS_REMOTE_REJECTED_REQUEST (502)
      - LS_UNKNOWN (500)
    """
    error_text = str(error)
    normalized_error = error_text.casefold()
    error_code = str(getattr(error, "error_code", "") or "").casefold()

    session_expired_patterns = (
        r"invalid\s+session\s+key",
        r"session\s+key[^.]*invalid",
        r"session[^.]*expired",
    )
    structured_status_error = isinstance(error, LimeSurveyStatusError)
    structured_session_error = structured_status_error and any(
        token in error_code for token in ("invalid_session", "session_expired", "invalidsession")
    )
    if structured_session_error or any(re.search(pattern, normalized_error) for pattern in session_expired_patterns):
        await delete_limesurvey_session(session_key)
        raise HTTPException(
            status_code=401,
            detail={
                "code": "LS_SESSION_EXPIRED",
                "message": "LimeSurvey session expired. Please login again.",
                "detail": error_text,
            },
        )

    if is_limesurvey_remote_unreachable(error):
        raise HTTPException(
            status_code=503,
            detail={
                "code": "LS_UNREACHABLE",
                "message": "LimeSurvey remote is unreachable.",
                "detail": f"{context}: {error_text}",
            },
        )

    if isinstance(error, (RPCInterfaceNotEnabledError, InvalidJSONResponseError)):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "LS_REMOTE_CONTROL_UNAVAILABLE",
                "message": "LimeSurvey RemoteControl 2 is disabled or did not return JSON.",
                "detail": error_text,
            },
        )

    if isinstance(error, (LimeSurveyStatusError, LimeSurveyApiError)):
        raise HTTPException(
            status_code=502,
            detail={
                "code": "LS_REMOTE_REJECTED_REQUEST",
                "message": "LimeSurvey rejected the RemoteControl 2 request.",
                "detail": error_text,
            },
        )

    raise HTTPException(
        status_code=500,
        detail={
            "code": "LS_UNKNOWN",
            "message": f"Unexpected LimeSurvey error while {context}.",
            "detail": error_text,
        },
    )
