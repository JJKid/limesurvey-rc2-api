import asyncio
import json
import pytest
from pydantic import ValidationError
from schemas import SurveyResponseDataset

from services.remote_response_loader import ResponseExportTooLargeError, load_responses


def test_dataset_rejects_nonfinite_values_in_nested_responses():
    with pytest.raises(ValidationError):
        SurveyResponseDataset(surveyId="synthetic", responses=[{"Q01": {"R1": float("nan")}}])


def test_dataset_matches_identifiers_to_response_rows():
    with pytest.raises(ValidationError):
        SurveyResponseDataset(surveyId="synthetic", responses=[{"Q01": "A1"}], responseIds=[])
    value = SurveyResponseDataset(surveyId="synthetic", responses=[{"Q01": "A1"}], responseIds=["capture-1"])
    assert value.responseIds == ["capture-1"]


class DummySurveyOperations:
    def __init__(self, content: bytes):
        self.content = content
        self.calls = []

    def export_responses(self, sid, **options):
        self.calls.append((sid, options))
        return self.content


class DummyApi:
    def __init__(self, content: bytes):
        self.survey = DummySurveyOperations(content)


def test_response_endpoint_returns_dataset_without_caching(client, auth_headers, monkeypatch):
    content = json.dumps({"responses": [{"Q01": "A1"}]}).encode()
    api = DummyApi(content)
    async def resume(_session_key, _auth): return api
    async def allow(_session_key, _sid): return None
    monkeypatch.setattr("routers.responses.resume_limesurvey_client", resume)
    monkeypatch.setattr("routers.responses.enforce_response_export_rate_limit", allow)

    response = client.get(
        "/survey_responses/123?language=es&completionStatus=complete&fields=Q01,Q02",
        headers={**auth_headers, "X-LimeSurvey-Session": "local-session"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "surveyId": "123",
        "language": "es",
        "responses": [{"Q01": "A1"}],
    }
    assert api.survey.calls == [(123, {
        "file_format": "json",
        "language": "es",
        "completion_status": "complete",
        "heading_type": "code",
        "response_type": "short",
        "from_response_id": None,
        "to_response_id": None,
        "fields": ["Q01", "Q02"],
    })]


def test_response_endpoint_returns_original_csv(client, auth_headers, monkeypatch):
    api = DummyApi(b"id,Q01\n1,A1\n")
    async def resume(_session_key, _auth): return api
    async def allow(_session_key, _sid): return None
    monkeypatch.setattr("routers.responses.resume_limesurvey_client", resume)
    monkeypatch.setattr("routers.responses.enforce_response_export_rate_limit", allow)

    response = client.get(
        "/survey_responses/123",
        headers={
            **auth_headers,
            "X-LimeSurvey-Session": "local-session",
            "Accept": "text/csv",
        },
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-type"].startswith("text/csv")
    assert response.content == b"id,Q01\n1,A1\n"


def test_response_endpoint_rejects_inverted_id_range(client, auth_headers):
    response = client.get(
        "/survey_responses/123?fromResponseId=20&toResponseId=10",
        headers={**auth_headers, "X-LimeSurvey-Session": "local-session"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_RESPONSE_RANGE"


def test_response_loader_rejects_oversized_export(monkeypatch):
    monkeypatch.setattr("services.remote_response_loader.LS_RESPONSES_MAX_BYTES", 4)
    api = DummyApi(b"12345")

    try:
        asyncio.run(load_responses(
            api=api,
            sid=123,
            file_format="csv",
            language=None,
            completion_status="all",
            heading_type="code",
            response_type="short",
            from_response_id=None,
            to_response_id=None,
            fields=None,
        ))
    except ResponseExportTooLargeError:
        return
    raise AssertionError("Expected ResponseExportTooLargeError")
