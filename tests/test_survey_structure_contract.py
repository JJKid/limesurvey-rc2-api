from unittest.mock import AsyncMock

import routers.survey_structures as survey_structures_router


def test_survey_structure_returns_the_importer_contract(client, auth_headers, monkeypatch):
    survey = {
        "sid": "123",
        "active": "Y",
        "format": "G",
        "language": "es",
        "showwelcome": "Y",
        "showprogress": "Y",
        "allowprev": "Y",
        "showgroupinfo": "B",
    }
    language = {
        "surveyls_title": "Contract survey",
        "surveyls_description": "Survey used to verify the adapter contract",
        "surveyls_endtext": "Completed",
    }
    groups = [{"gid": "10", "group_order": "1", "group_name": "General"}]
    questions = [{
        "sid": "123",
        "gid": "10",
        "qid": "100",
        "parent_qid": "0",
        "question_order": "1",
        "title": "Q_TEXT",
        "type": "S",
        "question": "Text question",
        "mandatory": "N",
        "relevance": "1",
        "result": {
            "question": "Text question",
            "answeroptions": None,
            "subquestions": None,
            "attributes": None,
        },
    }]

    monkeypatch.setattr(
        survey_structures_router,
        "resume_limesurvey_client",
        AsyncMock(return_value=object()),
    )

    async def load_result(_api, _sid, _language, refresh=False):
        assert refresh is False
        from services.survey_structure import build_survey_structure
        return build_survey_structure({
            "survey": survey,
            "language": language,
            "groups": groups,
            "questions": questions,
            "completion_context": {
                "active": True,
                "canSaveResponses": True,
                "submitMode": "submit",
                "language": "es",
                "endText": "Completed",
                "warningCodes": [],
                "didNotSaveCode": None,
            },
        }, source_format="remotecontrol")

    monkeypatch.setattr(survey_structures_router, "load_remote_survey_structure", load_result)

    response = client.get(
        "/survey_structure/123",
        headers={**auth_headers, "X-LimeSurvey-Session": "test-session"},
    )

    assert response.status_code == 200
    payload = response.json()
    survey_definition = payload["survey"]
    assert survey_definition["contractVersion"] == "2.0.0"
    assert survey_definition["id"] == "123"
    assert survey_definition["groups"][0]["id"] == "10"
    assert survey_definition["fields"][0]["source"]["questionId"] == "100"
    assert survey_definition["fields"][0]["type"] == "short-text"
    assert payload["issues"] == []
    assert payload["responseState"] == {
        "active": True,
        "canSaveResponses": True,
        "submitMode": "submit",
        "language": "es",
        "endText": "Completed",
        "warningCodes": [],
        "didNotSaveCode": None,
    }
