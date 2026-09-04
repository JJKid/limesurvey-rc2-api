import time

from jose import jwt

from core.config import (
    FORM_BUILDER_SERVICE_JWT_ISSUER,
    FORM_BUILDER_SERVICE_JWT_SECRET,
    JWT_ALGORITHM,
    JWT_AUDIENCE,
    JWT_TOKEN_TYPE,
)
from routers.surveys import _survey_list_cache_key


def test_survey_list_cache_key_does_not_expose_remote_session_key():
    class Api:
        url = "https://ls.example/admin/remotecontrol"
        username = "researcher"
        session_key = "remote-secret-session"

    key = _survey_list_cache_key(Api())

    assert key.startswith("ls:surveys:")
    assert "remote-secret-session" not in key
    assert "researcher" not in key


def test_smoke_endpoint(client):
    response = client.get("/smoke")
    assert response.status_code == 200
    payload = response.json()
    assert "app" in payload
    assert "env" in payload
    assert payload["remote_transport"] == "citric-requests"


def test_openapi_describes_only_supported_adapter_routes(client):
    document = client.get("/openapi.json").json()
    assert document["info"]["title"] == "LimeSurvey RemoteControl 2 Adapter"
    assert "/survey_structure/{sid}" in document["paths"]
    assert "/survey_structures/from-lss" in document["paths"]
    assert "/survey_questions/{sid}" not in document["paths"]
    assert "/survey_completion_context/{sid}" not in document["paths"]
    assert "InternalServiceJWT" in document["components"]["securitySchemes"]
    assert document["components"]["securitySchemes"]["InternalServiceJWT"]["scheme"] == "bearer"


def test_protected_route_rejects_missing_token(client):
    response = client.get("/surveys", headers={"X-LimeSurvey-Session": "x"})
    # Missing bearer token is handled explicitly by verify_token.
    assert response.status_code == 401


def test_protected_route_rejects_invalid_token(client):
    response = client.get(
        "/surveys",
        headers={
            "Authorization": "Bearer invalid-token",
            "X-LimeSurvey-Session": "x",
        },
    )
    assert response.status_code == 401


def test_protected_route_rejects_untrusted_issuer(client):
    token = jwt.encode(
        {
            "sub": "pytest-user", "iss": "untrusted-service", "aud": JWT_AUDIENCE,
            "iat": int(time.time()), "exp": int(time.time()) + 60,
        },
        FORM_BUILDER_SERVICE_JWT_SECRET,
        algorithm=JWT_ALGORITHM,
        headers={"typ": JWT_TOKEN_TYPE},
    )
    response = client.get(
        "/surveys",
        headers={
            "Authorization": f"Bearer {token}",
            "X-LimeSurvey-Session": "x",
        },
    )
    assert response.status_code == 401


def test_protected_route_rejects_wrong_audience(client):
    token = jwt.encode(
        {
            "sub": "pytest-user", "iss": FORM_BUILDER_SERVICE_JWT_ISSUER, "aud": "another-api",
            "iat": int(time.time()), "exp": int(time.time()) + 60,
        },
        FORM_BUILDER_SERVICE_JWT_SECRET,
        algorithm=JWT_ALGORITHM,
        headers={"typ": JWT_TOKEN_TYPE},
    )
    response = client.get(
        "/surveys",
        headers={
            "Authorization": f"Bearer {token}",
            "X-LimeSurvey-Session": "x",
        },
    )
    assert response.status_code == 401


def test_protected_route_requires_subject_expiration_and_internal_token_type(client):
    now = int(time.time())
    invalid_payloads = [
        ({"iss": FORM_BUILDER_SERVICE_JWT_ISSUER, "aud": JWT_AUDIENCE, "iat": now, "exp": now + 60}, JWT_TOKEN_TYPE),
        ({"sub": "user", "iss": FORM_BUILDER_SERVICE_JWT_ISSUER, "aud": JWT_AUDIENCE, "iat": now, "exp": now - 1}, JWT_TOKEN_TYPE),
        ({"sub": "user", "iss": FORM_BUILDER_SERVICE_JWT_ISSUER, "aud": JWT_AUDIENCE, "iat": now, "exp": now + 60}, "JWT"),
    ]
    for payload, token_type in invalid_payloads:
        token = jwt.encode(
            payload,
            FORM_BUILDER_SERVICE_JWT_SECRET,
            algorithm=JWT_ALGORITHM,
            headers={"typ": token_type},
        )
        response = client.get(
            "/surveys",
            headers={
                "Authorization": f"Bearer {token}",
                "X-LimeSurvey-Session": "x",
            },
        )
        assert response.status_code == 401


def test_surveys_timeout_returns_503(client, auth_headers, monkeypatch):
    class DummySurveyApi:
        session_key = "dummy-session"
        url = "https://ls.example.org/admin/remotecontrol"
        username = "reader"

        class survey:
            @staticmethod
            def list_surveys():
                time.sleep(0.05)
                return []

    monkeypatch.setattr("routers.surveys.LS_SURVEYS_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr("routers.surveys.resume_limesurvey_client", lambda session_key, auth: DummySurveyApi())
    monkeypatch.setattr("routers.surveys.cache_repository.get_json", lambda _key: None)

    response = client.get(
        "/surveys",
        headers={**auth_headers, "X-LimeSurvey-Session": "abc"},
    )
    assert response.status_code == 503, response.text
    payload = response.json()
    assert payload["detail"]["code"] == "LS_UNREACHABLE"
