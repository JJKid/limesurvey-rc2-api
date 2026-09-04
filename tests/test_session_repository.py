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
    )


def test_same_account_can_keep_independent_local_sessions(monkeypatch):
    monkeypatch.setattr("repositories.session_repository.cache_repository.get_json", lambda _key: None)
    monkeypatch.setattr("repositories.session_repository.cache_repository.set_json", lambda *_args: None)
    monkeypatch.setattr("repositories.session_repository.cache_repository.delete", lambda _key: None)
    session_repository.clear_memory_for_tests()

    session_repository.save("local-one", _record("remote-session-one"))
    session_repository.save("local-two", _record("remote-session-two"))

    assert session_repository.find("local-one").remote_session_key == "remote-session-one"
    assert session_repository.find("local-two").remote_session_key == "remote-session-two"

    session_repository.delete("local-one")
    assert session_repository.find("local-one") is None
    assert session_repository.find("local-two").remote_session_key == "remote-session-two"
    session_repository.delete("local-two")


def test_local_session_is_bound_to_subject_and_issuer(monkeypatch):
    monkeypatch.setattr("repositories.session_repository.cache_repository.get_json", lambda _key: None)
    monkeypatch.setattr("repositories.session_repository.cache_repository.set_json", lambda *_args: None)
    monkeypatch.setattr("repositories.session_repository.cache_repository.delete", lambda _key: None)
    session_repository.clear_memory_for_tests()
    session_repository.save("local-owned", _record("remote-session"))
    monkeypatch.setattr(
        "services.limesurvey_session_service.LimeSurveyClient.from_session_key",
        lambda **kwargs: kwargs,
    )

    api = resume_limesurvey_client(
        "local-owned",
        AuthenticatedIdentity(subject="user-1", issuer="form-builder-server"),
    )
    assert api["session_key"] == "remote-session"

    try:
        resume_limesurvey_client(
            "local-owned",
            AuthenticatedIdentity(subject="user-2", issuer="form-builder-server"),
        )
        assert False, "Expected a principal mismatch"
    except HTTPException as exc:
        assert exc.status_code == 403

    session_repository.delete("local-owned")
