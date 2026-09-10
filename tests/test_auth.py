def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json().get("detail") == "ok"

def test_login_fail(client, auth_headers):
    # An untrusted destination is rejected before any outbound connection.
    payload = {"url":"http://bad.url", "username":"x", "password":"y"}
    r = client.post("/login-limesurvey", json=payload, headers=auth_headers)
    assert r.status_code == 400
    assert r.json()["detail"]["code"] == "LIMESURVEY_URL_NOT_ALLOWED"

def test_login_and_logout_keep_remote_key_private(client, auth_headers, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, Mock
    import routers.auth as auth

    api = SimpleNamespace(session_key="synthetic-remote-key", open=Mock(), close=Mock())
    saved = AsyncMock()
    removed = AsyncMock()
    monkeypatch.setattr(auth, "validate_limesurvey_url", lambda url: url)
    monkeypatch.setattr(auth, "enforce_login_rate_limit", AsyncMock())
    monkeypatch.setattr(auth, "LimeSurveyClient", lambda **_kwargs: api)
    monkeypatch.setattr(auth, "store_limesurvey_session", saved)
    monkeypatch.setattr(auth, "resume_limesurvey_client", AsyncMock(return_value=api))
    monkeypatch.setattr(auth, "delete_limesurvey_session", removed)
    monkeypatch.setattr(auth, "LS_OPTIMIZER_ENABLED", False)

    response = client.post("/login-limesurvey", json={
        "url": "https://ls.example/rpc", "username": "test-reader", "password": "synthetic-password",
    }, headers=auth_headers)
    assert response.status_code == 200
    local_key = response.json()["session_key"]
    assert local_key != api.session_key
    assert api.session_key not in response.text
    assert saved.call_args.args == (local_key,)
    assert saved.call_args.kwargs["owner"].subject == "pytest-user"
    assert saved.call_args.kwargs["remote_session_key"] == api.session_key

    response = client.get("/logout-limesurvey", headers={**auth_headers, "X-LimeSurvey-Session": local_key})
    assert response.status_code == 200
    api.close.assert_called_once()
    removed.assert_awaited_once_with(local_key)
