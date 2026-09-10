"""
Shared Pydantic models and typed response aliases.

This file centralizes request/response contracts so routers can stay focused
on behavior and business flow.
"""

from typing import Any, Dict, List, Optional

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, JsonValue, model_validator


class LimeSurveyCredentials(BaseModel):
    """
    Credentials used by /login-limesurvey.
    """

    url: AnyHttpUrl = Field(
        ...,
        description="RemoteControl 2 URL ending in /admin/remotecontrol",
    )
    username: str
    password: str


class SessionKeyResp(BaseModel):
    session_key: str


class DetailResp(BaseModel):
    detail: str


class SurveyResponseDataset(BaseModel):
    """JSON-safe response rows exported from one LimeSurvey survey."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    surveyId: str
    language: Optional[str] = None
    responses: List[Dict[str, JsonValue]]
    responseIds: Optional[List[str]] = None

    @model_validator(mode="after")
    def matching_response_ids(self):
        if self.responseIds is not None and len(self.responseIds) != len(self.responses):
            raise ValueError("Each response must have a corresponding source identifier.")
        return self


SurveysResp = List[Dict[str, Any]]
QuestionsResp = List[Dict[str, Any]]
