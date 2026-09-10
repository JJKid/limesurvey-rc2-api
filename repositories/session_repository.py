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
    expires_at: float


_memory_sessions: Dict[str, LimeSurveySessionRecord] = {}
SESSION_EXPIRATION_INDEX = "ls:session-expirations"
SESSION_CLEANUP_GRACE_SECONDS = 300


def session_cache_key(local_session_id: str) -> str:
    """Build the private Redis key for one opaque local UUID."""
    return f"ls:session:{local_session_id}"


class SessionRepository:
    """Store sessions in Redis, with an explicit development-only fallback."""

    async def save(self, local_session_id: str, record: LimeSurveySessionRecord) -> None:
        await cache_repository.set_json(
            session_cache_key(local_session_id),
            asdict(record),
            LS_SESSION_TTL_SECONDS + SESSION_CLEANUP_GRACE_SECONDS,
        )
        await cache_repository.add_expiration(
            SESSION_EXPIRATION_INDEX,
            local_session_id,
            record.expires_at,
        )
        if ALLOW_IN_MEMORY_STATE:
            _memory_sessions[local_session_id] = record

    async def find(self, local_session_id: str) -> Optional[LimeSurveySessionRecord]:
        raw = await cache_repository.get_json(session_cache_key(local_session_id))
        if isinstance(raw, dict):
            try:
                record = LimeSurveySessionRecord(**raw)
                return record if record.expires_at > time.time() else None
            except TypeError:
                return None
        if not ALLOW_IN_MEMORY_STATE:
            return None
        fallback = _memory_sessions.get(local_session_id)
        if not fallback:
            return None
        if fallback.expires_at <= time.time():
            return None
        return fallback

    async def delete(self, local_session_id: str) -> None:
        await cache_repository.delete(session_cache_key(local_session_id))
        await cache_repository.remove_expiration(SESSION_EXPIRATION_INDEX, local_session_id)
        _memory_sessions.pop(local_session_id, None)

    async def take_expired(self, now: Optional[float] = None) -> list[tuple[str, LimeSurveySessionRecord]]:
        current = time.time() if now is None else now
        identifiers = await cache_repository.take_expired_members(SESSION_EXPIRATION_INDEX, current)
        if ALLOW_IN_MEMORY_STATE:
            identifiers.extend(
                identifier for identifier, record in _memory_sessions.items()
                if record.expires_at <= current and identifier not in identifiers
            )
        expired = []
        for identifier in identifiers:
            raw = await cache_repository.get_json(session_cache_key(identifier))
            record = None
            if isinstance(raw, dict):
                try:
                    record = LimeSurveySessionRecord(**raw)
                except TypeError:
                    record = None
            record = record or _memory_sessions.get(identifier)
            await cache_repository.delete(session_cache_key(identifier))
            _memory_sessions.pop(identifier, None)
            if record is not None:
                expired.append((identifier, record))
        return expired

    def clear_memory_for_tests(self) -> None:
        _memory_sessions.clear()


session_repository = SessionRepository()
