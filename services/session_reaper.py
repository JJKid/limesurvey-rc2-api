"""Close remote LimeSurvey sessions after their local authorization expires."""

import asyncio
import logging

from repositories.session_repository import session_repository
from services.limesurvey_client import LimeSurveyClient


logger = logging.getLogger(__name__)


async def run_session_reaper(stop: asyncio.Event, interval_seconds: float = 30.0) -> None:
    """Periodically claim expired sessions and close them once across workers."""
    while not stop.is_set():
        for local_session_id, record in await session_repository.take_expired():
            try:
                api = LimeSurveyClient.from_session_key(
                    url=record.url,
                    username=record.username,
                    session_key=record.remote_session_key,
                )
                await asyncio.to_thread(api.close)
            except Exception as exc:
                logger.warning(
                    "Could not close expired LimeSurvey session local_id_suffix=%s: %s",
                    local_session_id[-8:],
                    exc,
                )
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except asyncio.TimeoutError:
            pass
