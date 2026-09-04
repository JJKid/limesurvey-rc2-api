"""Create, authorize, resume, and remove LimeSurvey sessions."""

from fastapi import HTTPException

from core.security import AuthenticatedIdentity
from repositories.session_repository import (
    LimeSurveySessionRecord,
    session_repository,
)
from services.limesurvey_client import LimeSurveyClient


def store_limesurvey_session(
    local_session_id: str,
    *,
    url: str,
    username: str,
    remote_session_key: str,
    owner: AuthenticatedIdentity,
) -> None:
    """Persist a remote session under a local UUID bound to its caller."""
    session_repository.save(local_session_id, LimeSurveySessionRecord(
        url=url,
        username=username,
        remote_session_key=remote_session_key,
        owner_subject=owner.subject,
        owner_issuer=owner.issuer,
    ))


def resume_limesurvey_client(
    local_session_id: str,
    owner: AuthenticatedIdentity,
) -> LimeSurveyClient:
    """Authorize a local UUID and reconstruct its Citric-backed client."""
    record = session_repository.find(local_session_id)
    if record is None:
        raise HTTPException(status_code=401, detail="LimeSurvey session was not found or has expired")
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


def delete_limesurvey_session(local_session_id: str) -> None:
    """Remove one local-to-remote session association."""
    session_repository.delete(local_session_id)
