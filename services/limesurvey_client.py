"""Small Citric facade used by the LimeSurvey adapter API.

The rest of the service depends on ``LimeSurveyClient`` instead of Citric's
full public surface. Login, logout, request timeouts, and restoration of an
existing LimeSurvey session are therefore isolated in this module.
"""

from __future__ import annotations

from typing import Optional

from citric import Client
from models.limesurvey_remote import (
    LimeSurveyGroupRows,
    LimeSurveyPropertyMap,
    LimeSurveyQuestionRows,
    LimeSurveySurveyRows,
)
from services.citric_session_adapter import create_citric_client, resume_citric_client


class _SurveyOperations:
    """Expose the Citric survey operations used by this service."""

    def __init__(self, owner: "LimeSurveyClient") -> None:
        self._owner = owner

    def list_surveys(self) -> LimeSurveySurveyRows:
        """Return surveys visible to the authenticated LimeSurvey user."""
        return self._owner.client.list_surveys()

    def list_groups(self, survey_id: int, language: Optional[str] = None) -> LimeSurveyGroupRows:
        """Return a survey's question groups in the requested language."""
        return self._owner.client.list_groups(survey_id, language)

    def list_questions(
        self,
        survey_id: int,
        group_id: Optional[int] = None,
        language: Optional[str] = None,
    ) -> LimeSurveyQuestionRows:
        """Return survey questions, optionally filtered by group and language."""
        return self._owner.client.list_questions(survey_id, group_id, language)

    def get_survey_properties(self, survey_id: int, settings=None) -> LimeSurveyPropertyMap:
        """Return the requested survey-level properties."""
        return self._owner.client.get_survey_properties(survey_id, settings)

    def get_language_properties(
        self,
        survey_id: int,
        settings=None,
        language: Optional[str] = None,
    ) -> LimeSurveyPropertyMap:
        """Return localized survey text and properties."""
        return self._owner.client.get_language_properties(
            survey_id,
            settings=settings,
            language=language,
        )

    def export_responses(
        self,
        survey_id: int,
        *,
        file_format: str = "json",
        language: Optional[str] = None,
        completion_status: str = "all",
        heading_type: str = "code",
        response_type: str = "short",
        from_response_id: Optional[int] = None,
        to_response_id: Optional[int] = None,
        fields=None,
    ) -> bytes:
        """Export survey responses through Citric without caching their content."""
        return self._owner.client.export_responses(
            survey_id,
            file_format=file_format,
            language=language,
            completion_status=completion_status,
            heading_type=heading_type,
            response_type=response_type,
            from_response_id=from_response_id,
            to_response_id=to_response_id,
            fields=fields,
        )


class _QuestionOperations:
    """Expose the Citric question operations used by this service."""

    def __init__(self, owner: "LimeSurveyClient") -> None:
        self._owner = owner

    def get_question_properties(
        self,
        question_id: int,
        settings=None,
        language: Optional[str] = None,
    ) -> LimeSurveyPropertyMap:
        """Return detailed properties for one LimeSurvey question id."""
        return self._owner.client.get_question_properties(
            question_id,
            settings=settings,
            language=language,
        )


class LimeSurveyClient:
    """Expose only the Citric behavior required by the adapter API.

    Routers, caches, and optimizers remain independent from Citric internals.
    The facade can also restore a previously issued remote session key without
    storing or requesting the LimeSurvey password again.
    """

    def __init__(self, url: str, username: str) -> None:
        self.url = url
        self.username = username
        self._client: Optional[Client] = None
        self.survey = _SurveyOperations(self)
        self.question = _QuestionOperations(self)

    @property
    def client(self) -> Client:
        """Return the active Citric client or fail when no session is attached."""
        if self._client is None:
            raise RuntimeError("LimeSurvey client session is not open")
        return self._client

    @property
    def session_key(self) -> str:
        """Return the remote session key issued by LimeSurvey."""
        key = self.client.session.key
        if not key:
            raise RuntimeError("Citric did not provide a LimeSurvey session key")
        return key

    def open(self, password: str) -> None:
        """Log in to LimeSurvey and retain the resulting Citric client."""
        self._client = create_citric_client(self.url, self.username, password)

    @classmethod
    def from_session_key(
        cls,
        url: str,
        username: str,
        session_key: str,
    ) -> "LimeSurveyClient":
        """Build the facade around a previously stored remote session key."""
        instance = cls(url=url, username=username)
        instance._client = resume_citric_client(url, session_key)
        return instance

    def close(self) -> None:
        """Release the remote session in LimeSurvey."""
        self.client.close()
