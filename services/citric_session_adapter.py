"""Compatibility boundary for constructing and resuming Citric sessions."""

from __future__ import annotations

import json

import requests
from citric import Client
from citric.session import Session
from core.config import LS_REMOTE_CONNECT_TIMEOUT_SECONDS, LS_REMOTE_READ_TIMEOUT_SECONDS

DEFAULT_REMOTE_TIMEOUT = (
    LS_REMOTE_CONNECT_TIMEOUT_SECONDS,
    LS_REMOTE_READ_TIMEOUT_SECONDS,
)


class TimeoutHttpSession(requests.Session):
    """Apply a default timeout and disable redirects for every RC2 request."""

    def request(self, method, url, **kwargs):
        kwargs.setdefault("timeout", DEFAULT_REMOTE_TIMEOUT)
        kwargs.setdefault("allow_redirects", False)
        return super().request(method, url, **kwargs)


def create_citric_client(url: str, username: str, password: str) -> Client:
    """Create a supported Citric client and open a new remote session."""
    return Client(
        url,
        username,
        password,
        requests_session=TimeoutHttpSession(),
    )


def resume_citric_client(url: str, remote_session_key: str) -> Client:
    """Attach Citric 2.3.0 to a previously issued LimeSurvey session key.

    Citric 2.3.0 has no public constructor for this use case. All access to
    Citric private attributes remains isolated here and is protected by tests.
    """
    session = object.__new__(Session)
    session.url = url
    session._session = TimeoutHttpSession()  # type: ignore[attr-defined]
    session._session.headers["User-Agent"] = Session.USER_AGENT  # type: ignore[attr-defined]
    session._encoder = json.JSONEncoder  # type: ignore[attr-defined]
    setattr(session, "_Session__key", remote_session_key)
    setattr(session, "_Session__closed", False)

    client = object.__new__(Client)
    setattr(client, "_Client__session", session)
    setattr(client, "_Client__server_version", None)
    return client
