import asyncio
import json
from types import SimpleNamespace

import services.remote_survey_loader as remote_survey_loader
import services.remote_survey_structure_loader as remote_structure_loader


class _FakeRedisCache:
    def __init__(self, values):
        self.values = values
        self.saved = []

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.saved.append((key, value, ex))


class _FakeCacheRepository:
    def __init__(self, values):
        self.values = values
        self.saved = []

    def get_json(self, key):
        value = self.values.get(key)
        return json.loads(value) if isinstance(value, str) else value

    def set_json(self, key, value, ttl_seconds):
        self.values[key] = value
        self.saved.append((key, value, ttl_seconds))


def test_grouped_question_cache_is_scoped_by_limesurvey_account(monkeypatch):
    """Same survey ID from separate LS accounts must not return another account's cache."""
    sid = 123
    first_api = SimpleNamespace(
        url="https://first-limesurvey.example/index.php/admin/remotecontrol",
        username="first-reader",
        session_key="short-lived-first-session",
    )
    second_api = SimpleNamespace(
        url="https://second-limesurvey.example/index.php/admin/remotecontrol",
        username="second-reader",
        session_key="short-lived-second-session",
    )

    first_key = remote_survey_loader.build_grouped_questions_cache_key(first_api, sid)
    second_key = remote_survey_loader.build_grouped_questions_cache_key(second_api, sid)

    assert first_key == remote_survey_loader.build_grouped_questions_cache_key(first_api, sid)
    assert first_key != second_key
    assert "first-limesurvey.example" not in first_key
    assert "first-reader" not in first_key
    assert "short-lived-first-session" not in first_key
    assert remote_survey_loader.build_grouped_questions_cache_key(first_api, sid, "es") \
        != remote_survey_loader.build_grouped_questions_cache_key(first_api, sid, "en")

    cache = _FakeCacheRepository(
        {
            first_key: json.dumps([{"qid": "from-first-account"}]),
            second_key: json.dumps([{"qid": "from-second-account"}]),
        }
    )

    monkeypatch.setattr(remote_survey_loader, "cache_repository", cache)
    first_questions = asyncio.run(remote_survey_loader.load_questions(api=first_api, sid=sid))
    second_questions = asyncio.run(remote_survey_loader.load_questions(api=second_api, sid=sid))

    assert first_questions == [{"qid": "from-first-account"}]
    assert second_questions == [{"qid": "from-second-account"}]


def test_refresh_bypasses_grouped_question_cache_and_replaces_it(monkeypatch):
    class _SurveyOperations:
        @staticmethod
        def list_groups(_sid, _language):
            return [{"gid": "10", "grelevance": "1"}]

    api = SimpleNamespace(
        url="https://ls.example/admin/remotecontrol",
        username="reader",
        survey=_SurveyOperations(),
    )
    cache_key = remote_survey_loader.build_grouped_questions_cache_key(api, 123, "es")
    cache = _FakeCacheRepository({cache_key: [{"qid": "stale"}]})

    async def fetch_questions(_sid, _gid, _semaphore, _max_attempts, _language):
        return [{"qid": "fresh", "title": "Q1"}]

    async def fetch_properties(_qid, _semaphore, _max_attempts, _language):
        return {"condition": "1", "type": "S"}

    monkeypatch.setattr(remote_survey_loader, "cache_repository", cache)
    monkeypatch.setattr(
        remote_survey_loader,
        "get_cached_optimal_params",
        lambda _api: {"semaphore": 1, "maxAttempts": 1},
    )
    monkeypatch.setattr(
        remote_survey_loader,
        "make_fetchers",
        lambda _api: (fetch_questions, fetch_properties),
    )

    result = asyncio.run(remote_survey_loader.load_questions(api, 123, "es", refresh=True))

    assert result[0]["qid"] == "fresh"
    assert cache.values[cache_key][0]["qid"] == "fresh"


def test_available_languages_keeps_base_language_and_removes_duplicates():
    assert remote_structure_loader._available_languages({
        "language": "es",
        "additional_languages": "en, fr es",
    }) == ["es", "en", "fr"]


def test_remote_loader_enriches_groups_with_bounded_fetchers_and_caches(monkeypatch):
    class _SurveyOperations:
        @staticmethod
        def list_groups(sid, language):
            assert sid == 783587
            assert language == "es"
            return [{"gid": "10", "grelevance": "CONSENT == 'Y'"}]

    api = SimpleNamespace(
        url="https://ls.example/admin/remotecontrol",
        username="reader",
        survey=_SurveyOperations(),
    )
    cache = _FakeCacheRepository({})
    observed = {}

    async def fetch_questions(sid, gid, semaphore, max_attempts, language):
        observed["question_fetch"] = (sid, gid, max_attempts, language, semaphore._value)
        return [{"qid": "100", "title": "Q01"}]

    async def fetch_properties(qid, semaphore, max_attempts, language):
        observed["property_fetch"] = (qid, max_attempts, language, semaphore._value)
        return {"condition": "AGE >= 18", "type": "S"}

    monkeypatch.setattr(remote_survey_loader, "cache_repository", cache)
    monkeypatch.setattr(
        remote_survey_loader,
        "get_cached_optimal_params",
        lambda _api: {"semaphore": 3, "maxAttempts": 2},
    )
    monkeypatch.setattr(
        remote_survey_loader,
        "make_fetchers",
        lambda _api: (fetch_questions, fetch_properties),
    )

    result = asyncio.run(remote_survey_loader.load_questions(api, 783587, "es"))

    assert result == [{
        "qid": "100",
        "title": "Q01",
        "condition": "AGE >= 18",
        "type": "S",
        "grelevance": "CONSENT == 'Y'",
        "full_condition": "(CONSENT == 'Y') AND (AGE >= 18)",
    }]
    assert observed["question_fetch"] == (783587, "10", 2, "es", 3)
    assert observed["property_fetch"] == ("100", 2, "es", 3)
    assert cache.saved[0][2] == remote_survey_loader.QUESTIONS_CACHE_TTL_SECONDS


def test_remote_loader_reports_a_survey_without_groups(monkeypatch):
    class _SurveyOperations:
        @staticmethod
        def list_groups(_sid, _language):
            return []

    api = SimpleNamespace(url="https://ls.example", username="reader", survey=_SurveyOperations())
    monkeypatch.setattr(remote_survey_loader, "cache_repository", _FakeCacheRepository({}))
    monkeypatch.setattr(remote_survey_loader, "get_cached_optimal_params", lambda _api: None)

    try:
        asyncio.run(remote_survey_loader.load_questions(api, 123, "es"))
    except remote_survey_loader.SurveyGroupsNotFoundError as error:
        assert str(error) == "No groups found for survey ID 123"
    else:
        raise AssertionError("Expected SurveyGroupsNotFoundError")
