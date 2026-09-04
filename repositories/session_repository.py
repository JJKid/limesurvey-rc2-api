"""Persist local UUID to remote LimeSurvey session mappings."""

from dataclasses import asdict, dataclass
import time
from typing import Dict, Optional

from core.config import ALLOW_IN_MEMORY_STATE, LS_SESSION_TTL_SECONDS
from repositories.cache_repository import cache_repository


@dataclass(frozen=True)
class LimeSurveySessionRecord:
    """Data required to resume one remote session without storing a password."""

    url: str
    username: str
    remote_session_key: str
    owner_subject: str
    owner_issuer: str


_memory_sessions: Dict[str, tuple[float, LimeSurveySessionRecord]] = {}


def session_cache_key(local_session_id: str) -> str:
    """Build the private Redis key for one opaque local UUID."""
    return f"ls:session:{local_session_id}"


class SessionRepository:
    """Store sessions in Redis, with an explicit development-only fallback."""

    def save(self, local_session_id: str, record: LimeSurveySessionRecord) -> None:
        cache_repository.set_json(
            session_cache_key(local_session_id),
            asdict(record),
            LS_SESSION_TTL_SECONDS,
        )
        if ALLOW_IN_MEMORY_STATE:
            _memory_sessions[local_session_id] = (
                time.time() + LS_SESSION_TTL_SECONDS,
                record,
            )

    def find(self, local_session_id: str) -> Optional[LimeSurveySessionRecord]:
        raw = cache_repository.get_json(session_cache_key(local_session_id))
        if isinstance(raw, dict):
            try:
                return LimeSurveySessionRecord(**raw)
            except TypeError:
                return None
        if not ALLOW_IN_MEMORY_STATE:
            return None
        fallback = _memory_sessions.get(local_session_id)
        if not fallback:
            return None
        expires_at, record = fallback
        if expires_at <= time.time():
            self.delete(local_session_id)
            return None
        return record

    def delete(self, local_session_id: str) -> None:
        cache_repository.delete(session_cache_key(local_session_id))
        _memory_sessions.pop(local_session_id, None)

    def clear_memory_for_tests(self) -> None:
        _memory_sessions.clear()


session_repository = SessionRepository()
