import asyncio
import time

from fastapi import HTTPException

from core.security import AuthenticatedIdentity
from repositories.session_repository import (
    LimeSurveySessionRecord,
    session_repository,
)
from services.limesurvey_session_service import resume_limesurvey_client


def _record(remote_key: str, subject: str = "user-1") -> LimeSurveySessionRecord:
    return LimeSurveySessionRecord(
        url="https://ls.example.org/admin/remotecontrol",
        username="researcher",
        remote_session_key=remote_key,
        owner_subject=subject,
        owner_issuer="form-builder-server",
        expires_at=time.time() + 60,
    )


def test_same_account_can_keep_independent_local_sessions(monkeypatch):
    async def none(*_args): return None
    monkeypatch.setattr("repositories.session_repository.cache_repository.get_json", none)
    monkeypatch.setattr("repositories.session_repository.cache_repository.set_json", none)
    monkeypatch.setattr("repositories.session_repository.cache_repository.delete", none)
    monkeypatch.setattr("repositories.session_repository.cache_repository.add_expiration", none)
    monkeypatch.setattr("repositories.session_repository.cache_repository.remove_expiration", none)
    session_repository.clear_memory_for_tests()

    asyncio.run(session_repository.save("local-one", _record("remote-session-one")))
    asyncio.run(session_repository.save("local-two", _record("remote-session-two")))

    assert asyncio.run(session_repository.find("local-one")).remote_session_key == "remote-session-one"
    assert asyncio.run(session_repository.find("local-two")).remote_session_key == "remote-session-two"

    asyncio.run(session_repository.delete("local-one"))
    assert asyncio.run(session_repository.find("local-one")) is None
    assert asyncio.run(session_repository.find("local-two")).remote_session_key == "remote-session-two"
    asyncio.run(session_repository.delete("local-two"))


def test_local_session_is_bound_to_subject_and_issuer(monkeypatch):
    async def none(*_args): return None
    monkeypatch.setattr("repositories.session_repository.cache_repository.get_json", none)
    monkeypatch.setattr("repositories.session_repository.cache_repository.set_json", none)
    monkeypatch.setattr("repositories.session_repository.cache_repository.delete", none)
    monkeypatch.setattr("repositories.session_repository.cache_repository.add_expiration", none)
    monkeypatch.setattr("repositories.session_repository.cache_repository.remove_expiration", none)
    session_repository.clear_memory_for_tests()
    asyncio.run(session_repository.save("local-owned", _record("remote-session")))
    monkeypatch.setattr(
        "services.limesurvey_session_service.LimeSurveyClient.from_session_key",
        lambda **kwargs: kwargs,
    )

    api = asyncio.run(resume_limesurvey_client(
        "local-owned",
        AuthenticatedIdentity(subject="user-1", issuer="form-builder-server"),
    ))
    assert api["session_key"] == "remote-session"

    try:
        asyncio.run(resume_limesurvey_client(
            "local-owned",
            AuthenticatedIdentity(subject="user-2", issuer="form-builder-server"),
        ))
        assert False, "Expected a principal mismatch"
    except HTTPException as exc:
        assert exc.status_code == 403

    asyncio.run(session_repository.delete("local-owned"))


def test_expired_session_is_claimed_once_for_remote_cleanup(monkeypatch):
    async def none(*_args): return None
    async def no_claims(*_args): return []
    monkeypatch.setattr("repositories.session_repository.cache_repository.get_json", none)
    monkeypatch.setattr("repositories.session_repository.cache_repository.set_json", none)
    monkeypatch.setattr("repositories.session_repository.cache_repository.delete", none)
    monkeypatch.setattr("repositories.session_repository.cache_repository.add_expiration", none)
    monkeypatch.setattr("repositories.session_repository.cache_repository.remove_expiration", none)
    monkeypatch.setattr("repositories.session_repository.cache_repository.take_expired_members", no_claims)
    session_repository.clear_memory_for_tests()
    expired = LimeSurveySessionRecord(
        url="https://ls.example.org/admin/remotecontrol",
        username="researcher",
        remote_session_key="remote-expired",
        owner_subject="user-1",
        owner_issuer="form-builder-server",
        expires_at=time.time() - 1,
    )
    asyncio.run(session_repository.save("local-expired", expired))

    first = asyncio.run(session_repository.take_expired())
    second = asyncio.run(session_repository.take_expired())
    assert first == [("local-expired", expired)]
    assert second == []
