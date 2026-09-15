"""Synthetic failure/recovery checks; no remote services or credentials."""

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import BackgroundTasks, HTTPException

import routers.auth as auth
import services.remote_survey_loader as loader
import services.session_reaper as reaper
from core.security import AuthenticatedIdentity
from schemas import LimeSurveyCredentials


@pytest.mark.parametrize("message", ["Invalid session key", "Permission denied", "Invalid question"])
def test_property_failure_aborts_complete_load_without_caching(monkeypatch, message):
    api = SimpleNamespace(url="https://survey.example/rpc", username="synthetic-reader")
    cache = SimpleNamespace(get_json=AsyncMock(return_value=None), set_json=AsyncMock())
    questions = AsyncMock(return_value=[{"qid": "first"}, {"qid": "second"}])
    failure = RuntimeError(message)
    properties = AsyncMock(side_effect=[{"type": "S"}, failure])
    monkeypatch.setattr(loader, "cache_repository", cache)
    monkeypatch.setattr(loader, "get_cached_optimal_params", AsyncMock(return_value={"semaphore": 2, "maxAttempts": 1}))
    monkeypatch.setattr(loader, "make_fetchers", lambda _api: (questions, properties))

    with pytest.raises(RuntimeError, match=message):
        asyncio.run(loader.load_questions(api, 42, survey_groups=[{"gid": "group"}]))
    cache.set_json.assert_not_awaited()


def test_reaper_recovers_after_one_repository_outage_and_stops(monkeypatch, caplog):
    async def scenario():
        stop = asyncio.Event()
        calls = 0

        async def take_expired():
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ConnectionError("synthetic unavailable repository")
            stop.set()
            return []

        monkeypatch.setattr(reaper.session_repository, "take_expired", take_expired)
        await asyncio.wait_for(reaper.run_session_reaper(stop, interval_seconds=0.001), timeout=0.5)
        assert calls == 2

    asyncio.run(scenario())
    assert "synthetic unavailable repository" in caplog.text


def _configure_login(monkeypatch, api):
    monkeypatch.setattr(auth, "validate_limesurvey_url", lambda url: url)
    monkeypatch.setattr(auth, "enforce_login_rate_limit", AsyncMock())
    monkeypatch.setattr(auth, "LimeSurveyClient", lambda **_kwargs: api)
    monkeypatch.setattr(auth, "LS_OPTIMIZER_ENABLED", False)
    saved = AsyncMock()
    removed = AsyncMock()
    monkeypatch.setattr(auth, "store_limesurvey_session", saved)
    monkeypatch.setattr(auth, "delete_limesurvey_session", removed)
    return saved, removed


async def _login():
    return await auth.login_limesurvey(
        LimeSurveyCredentials(url="https://survey.example/rpc", username="reader", password="synthetic-password"),
        SimpleNamespace(client=SimpleNamespace(host="127.0.0.1")),
        BackgroundTasks(),
        AuthenticatedIdentity(subject="synthetic-owner", issuer="form-builder-server"),
    )


@pytest.mark.parametrize("abandonment", ["timeout", "cancel"])
def test_abandoned_login_closes_session_when_worker_finishes(monkeypatch, abandonment):
    started, finish, closed = threading.Event(), threading.Event(), threading.Event()

    def open_session(**_kwargs):
        started.set()
        assert finish.wait(1), "test did not release the synthetic worker"

    api = SimpleNamespace(session_key="synthetic-remote", open=Mock(side_effect=open_session), close=Mock(side_effect=closed.set))
    saved, _ = _configure_login(monkeypatch, api)
    monkeypatch.setattr(auth, "LS_LOGIN_TIMEOUT_SECONDS", 0.02 if abandonment == "timeout" else 1)

    async def scenario():
        task = asyncio.create_task(_login())
        assert await asyncio.to_thread(started.wait, 0.5)
        try:
            if abandonment == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await task
            else:
                with pytest.raises(HTTPException) as caught:
                    await task
                assert caught.value.status_code == 504
        finally:
            finish.set()
        assert await asyncio.to_thread(closed.wait, 0.5)

    asyncio.run(scenario())
    api.close.assert_called_once()
    saved.assert_not_awaited()


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_failed_session_write_compensates_remote_login_and_partial_local_state(monkeypatch, cleanup_fails):
    api = SimpleNamespace(session_key="synthetic-remote", open=Mock(), close=Mock())
    saved, removed = _configure_login(monkeypatch, api)
    failure = ConnectionError("synthetic failed session write")
    saved.side_effect = failure
    if cleanup_fails:
        api.close.side_effect = RuntimeError("synthetic close failure")
        removed.side_effect = ConnectionError("synthetic delete failure")
    with pytest.raises(ConnectionError, match="synthetic failed session write"):
        asyncio.run(_login())
    api.close.assert_called_once()
    removed.assert_awaited_once_with(saved.call_args.args[0])


def test_optional_optimizer_failure_does_not_discard_a_durably_saved_login(monkeypatch):
    api = SimpleNamespace(session_key="synthetic-remote", open=Mock(), close=Mock())
    saved, removed = _configure_login(monkeypatch, api)
    monkeypatch.setattr(auth, "LS_OPTIMIZER_ENABLED", True)
    monkeypatch.setattr(auth, "get_cached_optimal_params", AsyncMock(side_effect=ConnectionError("synthetic cache failure")))
    result = asyncio.run(_login())
    assert result.session_key == saved.call_args.args[0]
    api.close.assert_not_called()
    removed.assert_not_awaited()


@pytest.mark.parametrize("stage", ["store", "optimizer"])
def test_cancellation_after_remote_login_compensates_before_propagating(monkeypatch, stage):
    api = SimpleNamespace(session_key="synthetic-remote", open=Mock(), close=Mock())
    saved, removed = _configure_login(monkeypatch, api)
    async def scenario():
        entered = asyncio.Event()

        async def wait_forever(*_args, **_kwargs):
            entered.set()
            await asyncio.Event().wait()

        if stage == "store":
            saved.side_effect = wait_forever
        else:
            monkeypatch.setattr(auth, "LS_OPTIMIZER_ENABLED", True)
            monkeypatch.setattr(auth, "get_cached_optimal_params", wait_forever)
        task = asyncio.create_task(_login())
        await asyncio.wait_for(entered.wait(), timeout=0.5)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    api.close.assert_called_once()
    removed.assert_awaited_once_with(saved.call_args.args[0])
