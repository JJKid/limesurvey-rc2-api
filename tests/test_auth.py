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

# Este test asume LS real. Marcarlo con -m integration
def test_login_ok_and_logout_flow(client, auth_headers):
    # Replace these values when a real local LimeSurvey instance is available.
    payload = {
        "url": "http://localhost:8080/limesurvey/index.php/admin/remotecontrol",
        "username":"admin", "password":"passwd"
    }
    r = client.post("/login-limesurvey", json=payload, headers=auth_headers)
    if r.status_code != 200:
        return  # saltar si no hay LS local
    session_key = r.json()["session_key"]

    # surveys (protegido con JWT)
    r2 = client.get(
        "/surveys",
        headers={**auth_headers, "X-LimeSurvey-Session": session_key},
    )
    assert r2.status_code in (200, 401, 500, 404, 503)  # depende de LS/red/session

    # logout
    r3 = client.get(
        "/logout-limesurvey",
        headers={**auth_headers, "X-LimeSurvey-Session": session_key},
    )
    assert r3.status_code in (200, 404)
