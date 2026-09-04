"""Normalize LimeSurvey source rows into a validated SurveyLoadResult."""

from __future__ import annotations

import html
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from services.survey_structure.contract import (
    validate_survey_load_result,
    validate_survey_structure,
)
from services.survey_structure.condition_parser import (
    UnsupportedConditionError,
    build_condition_references,
    parse_limesurvey_condition,
)


CONTRACT_VERSION = "2.0.0"
QUESTION_TYPES = {
    "S": "short-text",
    "T": "long-text",
    "D": "date",
    "Y": "yes-no",
    "G": "gender",
    "L": "single-choice",
    "!": "single-choice",
    "O": "list-with-comment",
    "M": "multiple-choice",
    "P": "multiple-choice-with-comments",
    "N": "number",
    "F": "matrix",
    "H": "matrix",
    "B": "matrix",
    ";": "matrix",
    "Q": "multiple-input",
    "R": "ranking",
    "X": "display",
}


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
        field = _build_field(
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
    title = _text(language_data.get("surveyls_title") or payload.get("title")).strip()
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
    portable_groups = [_build_group(group, condition_references, issues) for group in groups]
    if portable_groups:
        ordered_groups = sorted(portable_groups, key=lambda group: group["order"])
        for index, group in enumerate(ordered_groups):
            group["order"] = index
        survey_structure["groups"] = ordered_groups
    settings = _build_settings(survey, language_data)
    if settings:
        survey_structure["settings"] = settings
    validated_survey = validate_survey_structure(survey_structure)
    load_result: Dict[str, Any] = {
        "survey": validated_survey,
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


def _build_field(
    question: Dict[str, Any],
    children: List[Dict[str, Any]],
    survey_id: str,
    language: str,
    issues: List[Dict[str, Any]],
    condition_references: Dict[str, tuple[str, Optional[str]]],
) -> Optional[Dict[str, Any]]:
    original_type = _text(question.get("type")).strip()
    field_type = QUESTION_TYPES.get(original_type)
    qid = _text(question.get("qid")).strip()
    code = _text(question.get("title")).strip()
    if not field_type:
        issues.append(_issue(
            "warning", "UNSUPPORTED_TYPE",
            f"LimeSurvey question type {original_type or '(missing)'} is not supported and was skipped.",
            field_id=qid, question_code=code,
            details={"sourceType": original_type},
        ))
        return None

    result = _record(question.get("result"))
    attributes = _record(result.get("attributes") or question.get("attributes"))
    localized = _localized_fixed_labels(language)
    label = _clean_html(question.get("question") or result.get("question") or "")
    help_text = _clean_html(question.get("help") or result.get("help") or "")
    options = _options(result.get("answeroptions") or question.get("answeroptions"))
    child_options = [
        {
            "code": _text(child.get("title")).strip() or f"SQ{index + 1:03d}",
            "label": _clean_html(child.get("question") or _record(child.get("result")).get("question") or child.get("title")),
            "order": index,
        }
        for index, child in enumerate(sorted(children, key=lambda item: _number(item.get("question_order"), 0)))
    ]
    subquestions = [
        {
            "id": _text(child.get("qid")).strip() or None,
            "code": option["code"],
            "label": option["label"],
            "order": option["order"],
        }
        for child, option in zip(sorted(children, key=lambda item: _number(item.get("question_order"), 0)), child_options)
    ]

    if original_type in {"M", "P"}:
        options = child_options
    elif original_type == "R" and not options:
        options = child_options
    elif original_type == "Y":
        options = [
            {"code": "Y", "label": localized["yes"], "order": 0},
            {"code": "N", "label": localized["no"], "order": 1},
        ]
    elif original_type == "G" and not options:
        options = [
            {"code": "F", "label": localized["female"], "order": 0},
            {"code": "M", "label": localized["male"], "order": 1},
        ]

    field: Dict[str, Any] = {
        "id": qid or code,
        "code": code,
        "type": field_type,
        "label": label,
        "required": _yes(question.get("mandatory")),
        "order": _number(question.get("question_order"), 0),
        "source": _compact({
            "platform": "limesurvey",
            "surveyId": survey_id,
            "groupId": _text(question.get("gid")).strip() or None,
            "questionId": qid or None,
            "nativeType": original_type,
            "extensions": ([_compact({
                "type": "limesurvey-question",
                "version": "1.0.0",
                "relevanceExpression": _text(question.get("relevance")).strip() or None,
                "fullConditionExpression": _text(question.get("full_condition")).strip() or None,
                "dateTimeFormat": _text(attributes.get("date_time_format")).strip() or None,
                "nativeValidation": _native_validation(attributes),
            })] if any(question.get(key) not in {None, ""} for key in (
                "relevance", "full_condition"
            )) or any(attributes.get(key) not in {None, ""} for key in (
                "date_time_format", "min_answers", "max_answers",
                "em_validation_q", "em_validation_sq",
            )) else None),
        }),
    }
    if field_type == "date":
        field["dateValueType"] = _date_value_type(attributes.get("date_time_format"))
        date_order = _date_order(attributes.get("date_time_format"))
        if date_order:
            field["rendering"] = {"dateOrder": date_order}
    group_id = _text(question.get("gid")).strip()
    parent_id = _text(question.get("parent_qid")).strip()
    if group_id:
        field["groupId"] = group_id
    if parent_id and parent_id != "0":
        field["parentId"] = parent_id
    if help_text:
        field["help"] = help_text
    default_value = _default_value(
        field_type,
        result.get("defaultvalue", question.get("defaultvalue")),
    )
    if default_value is not None:
        field["defaultValue"] = default_value
    visibility = _visibility(question, condition_references, issues, qid, code)
    if visibility:
        field["visibility"] = visibility
    validation = _validation(attributes, field_type, issues, qid, code)
    if validation:
        field["validation"] = validation
    if _yes(question.get("other")):
        field["other"] = {
            "code": "-oth-",
            "label": localized["other"],
            "textResponseKey": f"{code}_OTHER_value",
        }
        if original_type == "P":
            field["other"]["commentResponseKey"] = f"{code}_OTHER_comment"
    if original_type in {"M", "P"}:
        field["responseEncoding"] = {
            "selectedValue": "Y",
            "unselectedValue": "N",
            "selectedLabel": localized["yes"],
            "unselectedLabel": localized["no"],
        }

    if field_type in {"yes-no", "gender", "single-choice", "list-with-comment", "multiple-choice", "multiple-choice-with-comments", "ranking"}:
        field["options"] = options
        if not options:
            issues.append(_issue(
                "warning", "EMPTY_OPTIONS", f"Question {code} has no answer options.",
                field_id=qid, question_code=code,
            ))
    elif field_type == "multiple-input":
        field["subquestions"] = subquestions
    elif field_type == "matrix":
        rows = [option for child, option in zip(children, child_options) if _text(child.get("scale_id") or "0") == "0"]
        columns_from_children = [option for child, option in zip(children, child_options) if _text(child.get("scale_id")) == "1"]
        if original_type == "B":
            columns = [{"code": str(value), "label": str(value), "order": value - 1} for value in range(1, 11)]
        elif original_type == ";":
            columns = columns_from_children
        else:
            columns = options
        field["matrix"] = {
            "mode": "text" if original_type == ";" else "single",
            "rows": rows or child_options,
            "columns": columns,
        }
    return _compact(field)


def _native_validation(attributes: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Retain LimeSurvey-only validation text without treating it as portable behavior.

    Fixed numeric limits are also normalized into ``field.validation`` when the
    semantic field type supports them. Original expressions remain here so an
    importer report, diagnostic tool or future exporter can explain their
    source without forcing neutral consumers to understand ExpressionScript.
    """
    values = _compact({
        "minimumAnswersExpression": _text(attributes.get("min_answers")).strip() or None,
        "maximumAnswersExpression": _text(attributes.get("max_answers")).strip() or None,
        "questionValidationExpression": _text(attributes.get("em_validation_q")).strip() or None,
        "subquestionValidationExpression": _text(attributes.get("em_validation_sq")).strip() or None,
    })
    return values or None


def _build_group(
    group: Dict[str, Any],
    condition_references: Dict[str, tuple[str, Optional[str]]],
    issues: List[Dict[str, Any]],
) -> Dict[str, Any]:
    result = {
        "id": _text(group.get("gid")),
        "order": _number(group.get("group_order"), 0),
    }
    title = _clean_html(group.get("group_name"))
    description = _clean_html(group.get("description"))
    if title:
        result["title"] = title
    if description:
        result["description"] = description
    relevance = _text(group.get("grelevance")).strip()
    group_id = _text(group.get("gid")).strip()
    if group_id or relevance:
        result["source"] = _compact({
            "platform": "limesurvey",
            "groupId": group_id or None,
            "extensions": ([{
                "type": "limesurvey-group",
                "version": "1.0.0",
                "relevanceExpression": relevance,
            }] if relevance else None),
        })
    if relevance and relevance != "1":
        try:
            condition = parse_limesurvey_condition(relevance, condition_references)
            if condition:
                result["visibility"] = {"condition": condition}
        except UnsupportedConditionError as error:
            issues.append(_issue(
                "warning", "INVALID_EXPRESSION", str(error),
                details={"sourceExpression": relevance, "scope": "group"},
            ))
    return result


def _build_settings(survey: Dict[str, Any], language: Dict[str, Any]) -> Dict[str, Any]:
    layout = {"A": "all", "G": "group", "S": "question"}.get(_text(survey.get("format")).upper())
    show_group = _text(survey.get("showgroupinfo")).upper()
    return _compact({
        "layout": layout,
        "showWelcome": _yes(survey.get("showwelcome")) if survey.get("showwelcome") is not None else None,
        "showProgress": _yes(survey.get("showprogress")) if survey.get("showprogress") is not None else None,
        "allowPrevious": _yes(survey.get("allowprev")) if survey.get("allowprev") is not None else None,
        "showGroupName": show_group in {"B", "N"} if show_group else None,
        "showGroupDescription": show_group in {"B", "D"} if show_group else None,
        "questionIndex": {
            -1: "inherit",
            0: "disabled",
            1: "incremental",
            2: "full",
        }.get(int(_optional_number(survey.get("questionindex")) or 0)),
        # LimeSurvey can export -1 as an inherited/default sentinel. The
        # portable setting stores the effective non-negative delay instead.
        "navigationDelay": max(0, _optional_number(survey.get("navigationdelay")) or 0),
        "welcomeText": _clean_html(language.get("surveyls_welcometext")) or None,
        "endText": _clean_html(language.get("surveyls_endtext")) or None,
        "policyNotice": _clean_html(language.get("surveyls_policy_notice")) or None,
    })


def _validation(
    attributes: Dict[str, Any],
    field_type: str,
    issues: List[Dict[str, Any]],
    field_id: str,
    question_code: str,
) -> Dict[str, Any]:
    """Translate only validation rules that apply to the canonical field type.

    LimeSurvey exports some redundant attributes for field types that already
    enforce the same rule. For example, an ``L`` question can contain
    ``min_answers=1`` and ``max_answers=1`` even though single selection and
    ``mandatory`` already express those constraints. Copying every source
    attribute would create an invalid or misleading SurveyStructure.
    """
    validation: Dict[str, Any] = {}
    if field_type in {"number", "range"}:
        validation.update({
            "min": _optional_number(attributes.get("min_num_value") or attributes.get("minimum_answer")),
            "max": _optional_number(attributes.get("max_num_value") or attributes.get("maximum_answer")),
            "integer": (
                _yes(attributes.get("num_value_int_only"))
                if attributes.get("num_value_int_only") is not None
                else None
            ),
        })
    if field_type in {"multiple-choice", "multiple-choice-with-comments", "ranking"}:
        minimum = _validation_number(
            attributes.get("min_answers"), "min_answers", issues, field_id, question_code
        )
        maximum = _validation_number(
            attributes.get("max_answers"), "max_answers", issues, field_id, question_code
        )
        validation.update({
            "minSelections": minimum,
            "maxSelections": maximum,
        })
    return _compact(validation)


def _validation_number(
    value: Any,
    source_rule: str,
    issues: List[Dict[str, Any]],
    field_id: str,
    question_code: str,
) -> Optional[float]:
    """Read a numeric LimeSurvey validation value without inventing a fallback.

    LimeSurvey also permits dynamic expressions in some validation attributes.
    SurveyStructure currently represents only fixed numeric limits, so retain a
    visible warning instead of converting an expression to zero or silently
    treating it as a fixed rule.
    """
    if value is None or not _text(value).strip():
        return None
    parsed = _optional_number(value)
    if parsed is not None:
        return parsed
    issues.append(_issue(
        "warning",
        "INVALID_VALIDATION",
        f"Question {question_code} uses a dynamic {source_rule} expression that cannot be represented as a fixed numeric SurveyStructure validation.",
        field_id=field_id,
        question_code=question_code,
        details={"rule": source_rule, "sourceValue": value},
    ))
    return None


def _visibility(
    question: Dict[str, Any],
    condition_references: Dict[str, tuple[str, Optional[str]]],
    issues: List[Dict[str, Any]],
    field_id: str,
    question_code: str,
) -> Dict[str, Any]:
    full = _text(question.get("full_condition")).strip()
    relevance = _text(question.get("relevance")).strip()
    legacy_condition = _text(question.get("condition")).strip()
    # Group relevance is represented once on SurveyStructure.groups. Formly
    # combines it with this field-level condition when producing the runtime
    # projection, so it must not be copied into every field here.
    expression = next((candidate for candidate in (
        relevance,
        legacy_condition,
        full,
    ) if candidate and candidate != "1"), "")
    if not expression:
        return {}
    try:
        condition = parse_limesurvey_condition(expression, condition_references)
        return {"condition": condition} if condition else {}
    except UnsupportedConditionError as error:
        issues.append(_issue(
            "warning", "INVALID_EXPRESSION", str(error),
            field_id=field_id, question_code=question_code,
            details={"sourceExpression": expression},
        ))
        return {}


def _options(value: Any) -> List[Dict[str, Any]]:
    source = _record(value)
    result = []
    for index, (raw_code, raw_value) in enumerate(source.items()):
        row = _record(raw_value)
        code = _text(raw_code).strip()
        if not code:
            continue
        label = _clean_html(row.get("answer") or row.get("question") or row.get("label") or raw_value or code)
        result.append({
            "code": code,
            "label": label or code,
            "order": _number(row.get("order", row.get("sortorder")), index),
        })
    ordered = sorted(result, key=lambda item: item["order"])
    for index, item in enumerate(ordered):
        item["order"] = index
    return ordered


def _localized_fixed_labels(language: str) -> Dict[str, str]:
    """Return labels for fixed LimeSurvey values in the selected survey language."""
    if _text(language).lower().startswith("es"):
        return {
            "yes": "Sí",
            "no": "No",
            "other": "Otro",
            "female": "Femenino",
            "male": "Masculino",
        }
    return {
        "yes": "Yes",
        "no": "No",
        "other": "Other",
        "female": "Female",
        "male": "Male",
    }


def _date_value_type(source_format: Any) -> str:
    """Map a LimeSurvey date/time display format to its portable stored-value type."""
    value = _text(source_format).strip()
    if not value:
        return "date"
    lower = value.lower()
    has_day = "d" in lower
    has_month = "m" in lower
    has_year = "y" in lower
    has_time = "h" in lower
    if has_time and (has_day or has_month or has_year):
        return "date-time"
    if has_time:
        return "time"
    if has_year and has_month and not has_day:
        return "month-year"
    if has_year and not has_month and not has_day:
        return "year"
    return "date"


def _date_order(source_format: Any) -> Optional[str]:
    """Preserve whether a combined date/time control displays time before date."""
    value = _text(source_format).strip().lower()
    if _date_value_type(value) != "date-time":
        return None
    first_time = value.find("h")
    date_positions = [position for position in (value.find("d"), value.find("m"), value.find("y")) if position >= 0]
    return "time-date" if date_positions and first_time < min(date_positions) else "date-time"


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


def _clean_html(value: Any) -> str:
    raw = html.unescape(_text(value))
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    return re.sub(r"[ \t\r\f\v]+", " ", raw).strip()


def _issue(level: str, code: str, message: str, field_id: str = "", question_code: str = "", details: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return _compact({
        "level": level, "code": code, "message": message,
        "fieldId": field_id or None, "questionCode": question_code or None,
        "details": details or None,
    })


def _record(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else ([] if value is None else [value])


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _number(value: Any, fallback: float) -> float:
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return fallback


def _optional_number(value: Any) -> Optional[float]:
    if value is None or _text(value).strip() == "":
        return None
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError):
        return None


def _default_value(field_type: str, value: Any) -> Any:
    """Return the portable default-value shape required by one field variant."""
    if value is None or value == "":
        return None
    if field_type in {"display", "custom"}:
        return None
    if field_type in {"short-text", "long-text", "date"}:
        return _text(value)
    if field_type in {"number", "range"}:
        try:
            number = float(value)
            return int(number) if number.is_integer() else number
        except (TypeError, ValueError):
            return None
    if field_type == "boolean":
        return value if isinstance(value, bool) else _yes(value)
    if field_type in {"yes-no", "gender", "single-choice", "list-with-comment"}:
        return value if isinstance(value, (str, int, float, bool)) else None
    if field_type in {"multiple-choice", "multiple-choice-with-comments", "ranking"}:
        values = value if isinstance(value, list) else [value]
        return [item for item in values if isinstance(item, (str, int, float, bool))]
    if field_type in {"matrix", "multiple-input"}:
        return value if isinstance(value, dict) else None
    return None


def _yes(value: Any) -> bool:
    return _text(value).strip().upper() in {"Y", "1", "TRUE", "YES", "ON"}


def _compact(value: Dict[str, Any]) -> Dict[str, Any]:
    return {key: item for key, item in value.items() if item is not None and item != {}}
