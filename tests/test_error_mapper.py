import asyncio

from fastapi import HTTPException
from citric.exceptions import LimeSurveyStatusError, RPCInterfaceNotEnabledError

from services.error_mapper import is_limesurvey_remote_unreachable, raise_limesurvey_error


def test_is_limesurvey_remote_unreachable_by_timeout_type():
    assert is_limesurvey_remote_unreachable(TimeoutError("timeout"))


def test_is_limesurvey_remote_unreachable_by_known_pattern():
    error = Exception("HTTPConnectionPool: Max retries exceeded with url")
    assert is_limesurvey_remote_unreachable(error)


def test_raise_limesurvey_error_maps_unreachable_to_503():
    with_exception = Exception("connection refused while calling remote")
    try:
        asyncio.run(raise_limesurvey_error("abc-session", with_exception, "listing surveys"))
    except HTTPException as exc:
        assert exc.status_code == 503
        assert exc.detail["code"] == "LS_UNREACHABLE"
        assert "listing surveys" in exc.detail["detail"]
    else:
        assert False, "Expected HTTPException"


def test_raise_limesurvey_error_maps_unknown_to_500():
    try:
        asyncio.run(raise_limesurvey_error("abc-session", Exception("boom"), "listing surveys"))
    except HTTPException as exc:
        assert exc.status_code == 500
        assert exc.detail["code"] == "LS_UNKNOWN"
    else:
        assert False, "Expected HTTPException"


def test_raise_limesurvey_error_maps_invalid_session_to_401_and_clears_local_session(monkeypatch):
    deleted = {"key": None}

    async def fake_delete(session_key: str):
        deleted["key"] = session_key

    monkeypatch.setattr("services.error_mapper.delete_limesurvey_session", fake_delete)

    try:
        asyncio.run(raise_limesurvey_error("session-123", Exception("Invalid session key"), "any"))
    except HTTPException as exc:
        assert exc.status_code == 401
        assert exc.detail["code"] == "LS_SESSION_EXPIRED"
        assert deleted["key"] == "session-123"
    else:
        assert False, "Expected HTTPException"


def test_invalid_session_detection_is_case_insensitive(monkeypatch):
    deleted = []
    async def fake_delete(session_key: str):
        deleted.append(session_key)
    monkeypatch.setattr("services.error_mapper.delete_limesurvey_session", fake_delete)
    try:
        asyncio.run(raise_limesurvey_error(
            "session-lowercase",
            Exception("remote control returned INVALID SESSION KEY"),
            "listing surveys",
        ))
    except HTTPException as exc:
        assert exc.status_code == 401
        assert deleted == ["session-lowercase"]
    else:
        assert False, "Expected HTTPException"


def test_citric_status_error_is_returned_as_remote_502():
    try:
        asyncio.run(raise_limesurvey_error("session", LimeSurveyStatusError("Permission denied"), "reading survey"))
    except HTTPException as exc:
        assert exc.status_code == 502
        assert exc.detail["code"] == "LS_REMOTE_REJECTED_REQUEST"
    else:
        assert False, "Expected HTTPException"


def test_disabled_remote_control_has_a_specific_code():
    try:
        asyncio.run(raise_limesurvey_error("session", RPCInterfaceNotEnabledError(), "listing surveys"))
    except HTTPException as exc:
        assert exc.status_code == 502
        assert exc.detail["code"] == "LS_REMOTE_CONTROL_UNAVAILABLE"
    else:
        assert False, "Expected HTTPException"
