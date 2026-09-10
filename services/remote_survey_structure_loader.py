"""Build a complete SurveyLoadResult from one live LimeSurvey survey."""

from __future__ import annotations

import asyncio
import re
from collections import Counter
import logging
from typing import Any, Dict, Optional

from core.config import LS_SURVEY_LOAD_TIMEOUT_SECONDS
from services.remote_survey_loader import load_questions
from services.remote_call_executor import run_remote_call
from services.survey_structure import build_survey_structure


logger = logging.getLogger("uvicorn.error")

SURVEY_WIZARD_SETTINGS = [
    "sid",
    "active",
    "format",
    "showwelcome",
    "showprogress",
    "allowprev",
    "questionindex",
    "navigationdelay",
    "showgroupinfo",
    "language",
    "additional_languages",
]

SURVEY_LANGUAGE_SETTINGS = [
    "surveyls_title",
    "surveyls_description",
    "surveyls_welcometext",
    "surveyls_endtext",
    "surveyls_policy_notice",
]


async def load_remote_survey_structure(
    api: Any,
    sid: int,
    language: Optional[str] = None,
    refresh: bool = False,
) -> Dict[str, Any]:
    """Load remote survey parts, normalize them, and enforce a total timeout."""
    return await asyncio.wait_for(
        _load_remote_survey_structure(api, sid, language, refresh),
        timeout=LS_SURVEY_LOAD_TIMEOUT_SECONDS,
    )


async def _load_remote_survey_structure(
    api: Any,
    sid: int,
    language: Optional[str],
    refresh: bool,
) -> Dict[str, Any]:
    survey_properties = await _get_survey_properties(api, sid)
    selected_language = language or survey_properties.get("language")

    language_properties, groups = await asyncio.gather(
        _get_language_properties(api, sid, selected_language),
        _list_groups(api, sid, selected_language),
    )
    questions = await load_questions(
        api=api,
        sid=sid,
        language=selected_language,
        survey_groups=groups,
        refresh=refresh,
    )

    question_type_counts = Counter(str(question.get("type") or "") for question in questions)
    logger.info(
        "survey_structure normalized sid=%s groups=%s questions=%s language=%s question_types=%s",
        sid,
        len(groups),
        len(questions),
        selected_language,
        dict(question_type_counts),
    )

    source_payload = {
        "survey": survey_properties,
        "language": language_properties,
        "groups": groups,
        "questions": questions,
        "source": {
            "selectedLanguage": selected_language,
            "availableLanguages": _available_languages(survey_properties),
        },
        "completion_context": _build_response_state(survey_properties, language_properties),
    }
    return await asyncio.to_thread(build_survey_structure, source_payload, source_format="remotecontrol")


def _build_response_state(
    survey_properties: Dict[str, Any],
    language_properties: Dict[str, Any],
) -> Dict[str, Any]:
    """Represent whether the current LimeSurvey survey accepts responses."""
    is_active = str(survey_properties.get("active") or "").strip().upper() == "Y"
    return {
        "active": is_active,
        "canSaveResponses": is_active,
        "submitMode": "submit" if is_active else "submit_preview",
        "language": survey_properties.get("language"),
        "endText": language_properties.get("surveyls_endtext", "") or "",
        "warningCodes": [] if is_active else ["SURVEY_NOT_ACTIVE_PREVIEW"],
        "didNotSaveCode": None if is_active else "SURVEY_NOT_ACTIVE_NOT_RECORDED",
    }


async def _get_survey_properties(api: Any, sid: int) -> Dict[str, Any]:
    return await run_remote_call(api, api.survey.get_survey_properties, sid, SURVEY_WIZARD_SETTINGS)


async def _get_language_properties(
    api: Any,
    sid: int,
    language: Optional[str],
) -> Dict[str, Any]:
    return await run_remote_call(
        api,
        api.survey.get_language_properties,
        sid,
        SURVEY_LANGUAGE_SETTINGS,
        language,
    )


async def _list_groups(api: Any, sid: int, language: Optional[str]) -> list[Dict[str, Any]]:
    return await run_remote_call(api, api.survey.list_groups, sid, language)


def _available_languages(survey_properties: Dict[str, Any]) -> list[str]:
    values: list[str] = []
    base_language = str(survey_properties.get("language") or "").strip()
    if base_language:
        values.append(base_language)
    additional = survey_properties.get("additional_languages")
    candidates = additional if isinstance(additional, list) else re.split(
        r"[\s,;]+", str(additional or "").strip()
    )
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if normalized and normalized not in values:
            values.append(normalized)
    return values
