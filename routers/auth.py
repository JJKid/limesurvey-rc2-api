"""
Authentication/session lifecycle endpoints for LimeSurvey remote control.
"""

import asyncio
import logging
import threading
import uuid
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request

from core.config import LS_LOGIN_TIMEOUT_SECONDS, LS_OPTIMIZER_ENABLED
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
logger = logging.getLogger(__name__)


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
    await enforce_login_rate_limit(client_ip, credentials.username)

    try:
        trusted_url = await asyncio.to_thread(validate_limesurvey_url, str(credentials.url))
    except LimeSurveyUrlPolicyError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "LIMESURVEY_URL_NOT_ALLOWED", "message": str(exc)},
        ) from exc

    limesurvey_url = resolve_limesurvey_url_for_container(trusted_url)
    api = LimeSurveyClient(url=limesurvey_url, username=credentials.username)
    finished = threading.Event()
    abandoned = threading.Event()
    cleanup_lock = threading.Lock()
    cleanup_started = False

    def close_abandoned_session() -> None:
        nonlocal cleanup_started
        with cleanup_lock:
            if cleanup_started:
                return
            cleanup_started = True
        try:
            api.close()
        except Exception as exc:
            logger.warning("Could not close an abandoned LimeSurvey login (%s).", type(exc).__name__)

    def open_session() -> None:
        try:
            api.open(password=credentials.password)
        finally:
            # A cancelled asyncio waiter cannot stop its worker thread. The
            # worker owns late cleanup even if the request/event loop is gone.
            finished.set()
            if abandoned.is_set():
                close_abandoned_session()

    session_key = None
    try:
        try:
            await asyncio.wait_for(asyncio.to_thread(open_session), timeout=LS_LOGIN_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail=f"Login LS timeout after {int(LS_LOGIN_TIMEOUT_SECONDS)}s",
            ) from exc
        except Exception as exc:
            raise HTTPException(status_code=401, detail=f"LimeSurvey login failed: {exc}") from exc

        session_key = str(uuid.uuid4())
        await store_limesurvey_session(
            session_key,
            url=limesurvey_url,
            username=credentials.username,
            remote_session_key=api.session_key,
            owner=auth,
        )
        if LS_OPTIMIZER_ENABLED:
            try:
                if not await get_cached_optimal_params(api):
                    background.add_task(optimize_user_account_params, api)
            except Exception as exc:
                # Optional tuning must not hide a successfully persisted login.
                logger.warning("Login completed without optimizer scheduling (%s).", type(exc).__name__)
    except BaseException:
        abandoned.set()
        if finished.is_set():
            await asyncio.to_thread(close_abandoned_session)
        if session_key is not None:
            try:
                await delete_limesurvey_session(session_key)
            except Exception as exc:
                logger.warning("Could not remove a failed local session write (%s).", type(exc).__name__)
        raise

    return SessionKeyResp(session_key=session_key)


@router.get("/logout-limesurvey", response_model=DetailResp)
async def logout_limesurvey(
    session_key: str = Header(..., alias="X-LimeSurvey-Session"),
    auth: AuthenticatedIdentity = Depends(verify_token),
) -> DetailResp:
    """Close the remote session and delete its local key.

    Read the local key from ``X-LimeSurvey-Session``. Attempt the remote logout
    first, but remove local state even when LimeSurvey no longer responds.
    """
    api = await resume_limesurvey_client(session_key, auth)
    try:
        await asyncio.to_thread(api.close)
    except Exception:
        # Best-effort remote close; local cleanup must still happen.
        pass

    await delete_limesurvey_session(session_key)
    return DetailResp(detail="Session closed")
