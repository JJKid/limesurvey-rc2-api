import os
from pathlib import Path

import pytest

from services.survey_structure import survey_structure_from_lss

@pytest.mark.integration
def test_real_limesurvey_round_trip(client, auth_headers):
    """Open a real LS session, load one SurveyStructure, and close the session."""
    required = {
        "url": os.getenv("LS_INTEGRATION_URL"),
        "username": os.getenv("LS_INTEGRATION_USERNAME"),
        "password": os.getenv("LS_INTEGRATION_PASSWORD"),
        "sid": os.getenv("LS_INTEGRATION_SID"),
    }
    if any(not value for value in required.values()):
        pytest.skip(
            "Set LS_INTEGRATION_URL, LS_INTEGRATION_USERNAME, "
            "LS_INTEGRATION_PASSWORD, and LS_INTEGRATION_SID."
        )

    payload = {
        "url": required["url"],
        "username": required["username"],
        "password": required["password"],
    }
    login = client.post("/login-limesurvey", json=payload, headers=auth_headers)
    assert login.status_code == 200, login.text
    session_key = login.json()["session_key"]
    session_headers = {**auth_headers, "X-LimeSurvey-Session": session_key}
    try:
        response = client.get(
            f"/survey_structure/{required['sid']}",
            headers=session_headers,
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["survey"]["id"] == required["sid"]
        assert isinstance(result["survey"]["fields"], list)
        assert isinstance(result["issues"], list)
    finally:
        logout = client.get("/logout-limesurvey", headers=session_headers)
        assert logout.status_code == 200


@pytest.mark.integration
def test_lss_and_live_remotecontrol_have_the_same_supported_semantics(client, auth_headers):
    """Compare both source paths when credentials and the matching LSS are provided."""
    required = {
        "url": os.getenv("LS_INTEGRATION_URL"),
        "username": os.getenv("LS_INTEGRATION_USERNAME"),
        "password": os.getenv("LS_INTEGRATION_PASSWORD"),
        "sid": os.getenv("LS_INTEGRATION_SID"),
        "lss": os.getenv("LS_INTEGRATION_LSS"),
    }
    if any(not value for value in required.values()):
        pytest.skip("Set the LS_INTEGRATION_* variables, including LS_INTEGRATION_LSS.")

    local_result = survey_structure_from_lss(Path(required["lss"]).read_bytes())
    language = local_result["survey"].get("language")
    login = client.post(
        "/login-limesurvey",
        json={
            "url": required["url"],
            "username": required["username"],
            "password": required["password"],
        },
        headers=auth_headers,
    )
    assert login.status_code == 200, login.text
    session_headers = {
        **auth_headers,
        "X-LimeSurvey-Session": login.json()["session_key"],
    }
    try:
        remote = client.get(
            f"/survey_structure/{required['sid']}",
            params={"language": language, "refresh": "true"},
            headers=session_headers,
        )
        assert remote.status_code == 200, remote.text
        assert _supported_semantic_projection(remote.json()["survey"]) == \
            _supported_semantic_projection(local_result["survey"])
    finally:
        client.get("/logout-limesurvey", headers=session_headers)


def _supported_semantic_projection(survey):
    """Exclude transport-only provenance while comparing supported survey behavior."""
    field_keys = {
        "id", "code", "type", "label", "groupId", "parentId", "help",
        "required", "order", "defaultValue", "validation", "visibility",
        "rendering", "responseEncoding", "options", "subquestions", "matrix", "other",
        "dateValueType", "childrenFields",
    }
    return {
        "id": survey["id"],
        "title": survey.get("title"),
        "description": survey.get("description"),
        "language": survey.get("language"),
        "groups": [
            {key: value for key, value in group.items() if key != "source"}
            for group in survey.get("groups", [])
        ],
        "fields": [
            {key: value for key, value in field.items() if key in field_keys}
            for field in survey["fields"]
        ],
        "settings": survey.get("settings"),
    }
