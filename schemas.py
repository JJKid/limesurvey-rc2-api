"""
Shared Pydantic models and typed response aliases.

This file centralizes request/response contracts so routers can stay focused
on behavior and business flow.
"""

from typing import Any, Dict, List

from pydantic import AnyHttpUrl, BaseModel, Field


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


SurveysResp = List[Dict[str, Any]]
QuestionsResp = List[Dict[str, Any]]
