"""Compose normalized LimeSurvey fields and groups into a validated SurveyLoadResult."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional
from .contract import validate_survey_load_result
from .condition_parser import UnsupportedConditionError, build_condition_references, parse_limesurvey_condition
from .source_values import _record, _list, _text, _number, _optional_number, _clean_html, _issue, _yes, _compact
from .field_normalizer import normalize_field
from .survey_settings import normalize_group, normalize_settings

CONTRACT_VERSION = "2.0.0"


class SurveyStructureSourceError(ValueError):
    """The source cannot produce a valid SurveyStructure."""


def build_survey_structure(payload: Dict[str, Any], source_format: str = "remotecontrol") -> Dict[str, Any]:
    """Normalize LimeSurvey data into a validated survey load result."""
    survey = _record(payload.get("survey"))
    language_data = _record(payload.get("language"))
    groups = [_record(item) for item in _list(payload.get("groups")) if _record(item)]
    questions = [_normalize_question(_record(item)) for item in _list(payload.get("questions")) if _record(item)]
    source = _record(payload.get("source"))
    issues: List[Dict[str, Any]] = list(_list(payload.get("issues")))

    survey_id = _text(survey.get("sid") or source.get("surveyId") or payload.get("id")).strip()
    if not survey_id:
        raise SurveyStructureSourceError("LimeSurvey source does not contain a survey id.")

    children_by_parent: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    top_level: List[Dict[str, Any]] = []
    for question in questions:
        parent_id = _text(question.get("parent_qid") or "0").strip()
        if parent_id in {"", "0"}:
            top_level.append(question)
        else:
            children_by_parent[parent_id].append(question)

    condition_references = build_condition_references(questions, survey_id)
    selected_language = _text(
        source.get("selectedLanguage")
        or survey.get("language")
        or payload.get("selected_language")
    ).strip()

    top_level_ids = {_text(question.get("qid")) for question in top_level}
    for parent_id, children in children_by_parent.items():
        if parent_id not in top_level_ids:
            for child in children:
                issues.append(_issue(
                    "warning", "MISSING_PARENT",
                    f"Subquestion {_text(child.get('qid'))} references missing parent {parent_id}.",
                    field_id=_text(child.get("qid")),
                ))

    group_order = {
        _text(group.get("gid")): _number(group.get("group_order"), _number(group.get("gid"), 0))
        for group in groups
    }
    top_level.sort(key=lambda question: (
        group_order.get(_text(question.get("gid")), _number(question.get("gid"), 0)),
        _number(question.get("question_order"), 0),
    ))

    fields: List[Dict[str, Any]] = []
    seen_codes = set()
    for question in top_level:
        code = _text(question.get("title")).strip()
        qid = _text(question.get("qid")).strip()
        if not code:
            issues.append(_issue(
                "error", "MISSING_QUESTION_CODE",
                f"Question {qid or '(without id)'} has no code and was skipped.",
                field_id=qid,
            ))
            continue
        if code in seen_codes:
            issues.append(_issue(
                "error", "DUPLICATE_QUESTION_CODE",
                f"Question code {code} is duplicated and the later question was skipped.",
                field_id=qid, question_code=code,
            ))
            continue
        seen_codes.add(code)
        field = normalize_field(
            question,
            children_by_parent.get(qid, []),
            survey_id,
            selected_language,
            issues,
            condition_references,
        )
        if field:
            field["order"] = len(fields)
            fields.append(field)

    available_languages = [str(item) for item in _list(source.get("availableLanguages")) if _text(item).strip()]
    title = _clean_html(language_data.get("surveyls_title") or payload.get("title"))
    description = _clean_html(language_data.get("surveyls_description") or payload.get("description"))
    survey_structure: Dict[str, Any] = {
        "contractVersion": CONTRACT_VERSION,
        "id": survey_id,
        "fields": fields,
        "source": _compact({
            "platform": "limesurvey",
            "format": source_format,
            # A LimeSurvey DBVersion is a database-schema revision, not the
            # product version. Keep it in the typed extension instead.
            "version": _text(source.get("version")).strip() or None,
            "extensions": ([_compact({
                "type": "limesurvey-survey",
                "version": "1.0.0",
                "databaseSchemaVersion": _text(source.get("databaseSchemaVersion")).strip() or None,
            })] if source.get("databaseSchemaVersion") else None),
        }),
    }
    if title:
        survey_structure["title"] = title
    if description:
        survey_structure["description"] = description
    if selected_language:
        survey_structure["language"] = selected_language
    if available_languages:
        survey_structure["availableLanguages"] = available_languages
    portable_groups = [normalize_group(group, condition_references, issues) for group in groups]
    if portable_groups:
        ordered_groups = sorted(portable_groups, key=lambda group: group["order"])
        for index, group in enumerate(ordered_groups):
            group["order"] = index
        survey_structure["groups"] = ordered_groups
    settings = normalize_settings(survey, language_data)
    if settings:
        survey_structure["settings"] = settings
    load_result: Dict[str, Any] = {
        "survey": survey_structure,
        "issues": issues,
    }
    completion_context = _record(payload.get("completion_context"))
    if completion_context:
        load_result["responseState"] = {
            "active": bool(completion_context.get("active", False)),
            "canSaveResponses": bool(completion_context.get("canSaveResponses", False)),
            "submitMode": completion_context.get("submitMode", "submit_preview"),
            "warningCodes": _list(completion_context.get("warningCodes")),
            "didNotSaveCode": completion_context.get("didNotSaveCode"),
        }
        if completion_context.get("language"):
            load_result["responseState"]["language"] = completion_context["language"]
        if completion_context.get("endText"):
            load_result["responseState"]["endText"] = completion_context["endText"]
    return validate_survey_load_result(load_result)


def _normalize_question(question: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(question)
    result = _record(normalized.get("result"))
    for key in ("answeroptions", "subquestions", "available_answers", "attributes", "attributes_lang"):
        value = result.get(key, normalized.get(key))
        if isinstance(value, str) and value.strip().lower().startswith("no available "):
            value = None
        if key in result:
            result[key] = value
        if key in normalized:
            normalized[key] = value
    normalized["result"] = result
    return normalized
