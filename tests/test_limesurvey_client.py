import asyncio
import json
import requests

from services import citric_session_adapter, limesurvey_client
from services.limesurvey_fetchers import make_fetchers


class FakeSession:
    key = "remote-session"

    def rpc(self, method, *params):
        return {"method": method, "params": list(params)}


class FakeCitricClient:
    def __init__(self, url, username, password, *, requests_session=None):
        self.created_with = (url, username, password)
        self.requests_session = requests_session
        self.session = FakeSession()
        self.closed = False

    def close(self):
        self.closed = True

    def list_surveys(self):
        return [{"sid": 1}]

    def list_groups(self, survey_id, language=None):
        return [{"gid": 2, "sid": survey_id, "language": language}]

    def list_questions(self, survey_id, group_id=None, language=None):
        return [{"qid": 3, "sid": survey_id, "gid": group_id, "language": language}]

    def get_survey_properties(self, survey_id, settings=None):
        return {"sid": survey_id, "settings": settings}

    def get_language_properties(self, survey_id, *, settings=None, language=None):
        return {"sid": survey_id, "settings": settings, "language": language}

    def get_question_properties(self, question_id, *, settings=None, language=None):
        return {"qid": question_id, "settings": settings, "language": language}


def test_citric_facade_keeps_the_existing_fastapi_operations(monkeypatch):
    monkeypatch.setattr(citric_session_adapter, "Client", FakeCitricClient)
    monkeypatch.setattr(limesurvey_client, "create_citric_client", citric_session_adapter.create_citric_client)
    api = limesurvey_client.LimeSurveyClient("https://ls.example/rpc", "researcher")

    api.open("secret")

    assert api.session_key == "remote-session"
    assert isinstance(api.client.requests_session, citric_session_adapter.TimeoutHttpSession)
    assert api.survey.list_surveys() == [{"sid": 1}]
    assert api.survey.list_groups(1, "es")[0]["language"] == "es"
    assert api.survey.list_questions(1, 2)[0]["qid"] == 3
    assert api.survey.get_survey_properties(1, ["active"])["settings"] == ["active"]
    assert api.survey.get_language_properties(1, ["title"], "es")["language"] == "es"
    assert api.question.get_question_properties(3)["qid"] == 3
    api.close()
    assert api.client.closed is True


def test_citric_session_can_be_resumed_without_persisting_password(monkeypatch):
    captured = {}

    class FakeResponse:
        text = "json-rpc-response"

        def __init__(self, request_id):
            self.request_id = request_id

        def raise_for_status(self):
            return None

        def json(self):
            return {"id": self.request_id, "result": [{"qid": 3}], "error": None}

    def fake_post(_session, url, **kwargs):
        captured["url"] = url
        captured["payload"] = json.loads(kwargs["data"])
        return FakeResponse(captured["payload"]["id"])

    monkeypatch.setattr(citric_session_adapter.TimeoutHttpSession, "post", fake_post)
    api = limesurvey_client.LimeSurveyClient.from_session_key(
        "https://ls.example/rpc",
        "researcher",
        "existing-remote-key",
    )

    assert api.session_key == "existing-remote-key"
    assert not hasattr(api, "password")
    assert api.survey.list_questions(1, 2) == [{"qid": 3}]
    assert captured["url"] == "https://ls.example/rpc"
    assert captured["payload"]["method"] == "list_questions"
    assert captured["payload"]["params"] == ["existing-remote-key", 1, 2, None]


def test_fetchers_keep_semaphore_and_retries_around_citric_calls(monkeypatch):
    monkeypatch.setattr(citric_session_adapter, "Client", FakeCitricClient)
    monkeypatch.setattr(limesurvey_client, "create_citric_client", citric_session_adapter.create_citric_client)
    api = limesurvey_client.LimeSurveyClient("https://ls.example/rpc", "researcher")
    api.open("secret")
    fetch_questions, fetch_properties = make_fetchers(api)

    async def run():
        semaphore = asyncio.Semaphore(1)
        questions = await fetch_questions(1, 2, semaphore, max_attempts=2, language="es")
        properties = await fetch_properties(3, semaphore, max_attempts=2, language="es")
        return questions, properties

    questions, properties = asyncio.run(run())
    assert questions[0]["qid"] == 3
    assert questions[0]["language"] == "es"
    assert properties["qid"] == 3
    assert properties["language"] == "es"


def test_fetcher_does_not_sleep_after_the_last_failed_attempt(monkeypatch):
    sleeps = []

    class FailingQuestionOperations:
        @staticmethod
        def list_questions(*_args):
            raise requests.Timeout("temporary timeout")

    api = type("Api", (), {
        "url": "https://ls.example/rpc",
        "username": "reader",
        "survey": FailingQuestionOperations(),
    })()
    fetch_questions, _ = make_fetchers(api)

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr("services.limesurvey_fetchers.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("services.limesurvey_fetchers.random.uniform", lambda *_args: 0)

    async def run():
        try:
            await fetch_questions(1, 2, asyncio.Semaphore(1), max_attempts=3)
        except requests.Timeout:
            return
        assert False, "Expected the final timeout"

    asyncio.run(run())
    assert sleeps == [1, 2]
