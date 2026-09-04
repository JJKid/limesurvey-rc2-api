"""
Authentication/session lifecycle endpoints for LimeSurvey remote control.
"""

import asyncio
import uuid
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request

from core.config import LS_LOGIN_TIMEOUT_SECONDS
from core.limesurvey_url import LimeSurveyUrlPolicyError, validate_limesurvey_url
from core.security import AuthenticatedIdentity, verify_token
from schemas import DetailResp, LimeSurveyCredentials, SessionKeyResp
from services.optimizer_service import get_cached_optimal_params, optimize_user_account_params
from services.login_rate_limiter import enforce_login_rate_limit
from services.limesurvey_client import LimeSurveyClient
from services.limesurvey_session_service import (
    delete_limesurvey_session,
    resume_limesurvey_client,
    store_limesurvey_session,
)


router = APIRouter(tags=["limesurvey-sessions"])


def resolve_limesurvey_url_for_container(url: str) -> str:
    """
    Docker containers resolve localhost to themselves. When the user enters a
    host-local LimeSurvey URL, route it through Docker Desktop's host alias.
    """
    parsed = urlsplit(url)
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        return url

    netloc = "host.docker.internal"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"

    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


@router.post("/login-limesurvey", response_model=SessionKeyResp)
async def login_limesurvey(
    credentials: LimeSurveyCredentials,
    request: Request,
    background: BackgroundTasks,
    auth: AuthenticatedIdentity = Depends(verify_token),
) -> SessionKeyResp:
    """Open a LimeSurvey session and return an opaque local key.

    Receive the RemoteControl 2 URL, username, and password. Citric obtains the
    remote key from LimeSurvey. This service stores it temporarily and returns
    a different local key for subsequent requests.
    """
    client_ip = request.client.host if request.client else 'unknown'
    enforce_login_rate_limit(client_ip, credentials.username)

    try:
        trusted_url = await asyncio.to_thread(validate_limesurvey_url, str(credentials.url))
    except LimeSurveyUrlPolicyError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "LIMESURVEY_URL_NOT_ALLOWED", "message": str(exc)},
        ) from exc

    limesurvey_url = resolve_limesurvey_url_for_container(trusted_url)
    api = LimeSurveyClient(url=limesurvey_url, username=credentials.username)
    try:
        await asyncio.wait_for(
            asyncio.to_thread(api.open, password=credentials.password),
            timeout=LS_LOGIN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=f"Login LS timeout after {int(LS_LOGIN_TIMEOUT_SECONDS)}s",
        )
    except Exception as exc:
        raise HTTPException(status_code=401, detail=f"LimeSurvey login failed: {exc}")

    session_key = str(uuid.uuid4())
    store_limesurvey_session(
        session_key,
        url=limesurvey_url,
        username=credentials.username,
        remote_session_key=api.session_key,
        owner=auth,
    )

    if not get_cached_optimal_params(api):
        background.add_task(optimize_user_account_params, api)

    return SessionKeyResp(session_key=session_key)


@router.get("/logout-limesurvey", response_model=DetailResp)
def logout_limesurvey(
    session_key: str = Header(..., alias="X-LimeSurvey-Session"),
    auth: AuthenticatedIdentity = Depends(verify_token),
) -> DetailResp:
    """Close the remote session and delete its local key.

    Read the local key from ``X-LimeSurvey-Session``. Attempt the remote logout
    first, but remove local state even when LimeSurvey no longer responds.
    """
    api = resume_limesurvey_client(session_key, auth)
    try:
        api.close()
    except Exception:
        # Best-effort remote close; local cleanup must still happen.
        pass

    delete_limesurvey_session(session_key)
    return DetailResp(detail="Session closed")
