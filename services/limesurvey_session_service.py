"""Create, authorize, resume, and remove LimeSurvey sessions."""

from fastapi import HTTPException
import time

from core.config import LS_SESSION_TTL_SECONDS
from core.security import AuthenticatedIdentity
from repositories.session_repository import (
    LimeSurveySessionRecord,
    session_repository,
)
from services.limesurvey_client import LimeSurveyClient


async def store_limesurvey_session(
    local_session_id: str,
    *,
    url: str,
    username: str,
    remote_session_key: str,
    owner: AuthenticatedIdentity,
) -> None:
    """Persist a remote session under a local UUID bound to its caller."""
    await session_repository.save(local_session_id, LimeSurveySessionRecord(
        url=url,
        username=username,
        remote_session_key=remote_session_key,
        owner_subject=owner.subject,
        owner_issuer=owner.issuer,
        expires_at=time.time() + LS_SESSION_TTL_SECONDS,
    ))


async def resume_limesurvey_client(
    local_session_id: str,
    owner: AuthenticatedIdentity,
) -> LimeSurveyClient:
    """Authorize a local UUID and reconstruct its Citric-backed client."""
    record = await session_repository.find(local_session_id)
    if record is None:
        raise HTTPException(status_code=401, detail={
            "code": "LS_SESSION_EXPIRED",
            "message": "LimeSurvey session was not found or has expired. Open a new session.",
        })
    if (
        record.owner_subject != owner.subject
        or record.owner_issuer != owner.issuer
    ):
        raise HTTPException(
            status_code=403,
            detail="LimeSurvey session belongs to another authenticated identity",
        )
    return LimeSurveyClient.from_session_key(
        url=record.url,
        username=record.username,
        session_key=record.remote_session_key,
    )


async def delete_limesurvey_session(local_session_id: str) -> None:
    """Remove one local-to-remote session association."""
    await session_repository.delete(local_session_id)
