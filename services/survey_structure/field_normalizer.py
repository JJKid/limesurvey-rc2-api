"""Convert one LimeSurvey question, its options and field rules into SurveyStructure."""

from typing import Any, Dict, List, Optional
from .source_values import _clean_html, _issue, _record, _text, _number, _optional_number, _yes, _compact
from .visibility_normalizer import normalize_field_visibility


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
    ":": "matrix",
    "1": "matrix",
    "H": "matrix",
    "B": "matrix",
    ";": "matrix",
    "Q": "multiple-input",
    "R": "ranking",
    "X": "display",
}


def normalize_field(
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
    # Pair each option with its own source row, even when scales interleave by order.
    children = sorted(children, key=lambda item: _number(item.get("question_order"), 0))
    child_options = [
        {
            "code": _text(child.get("title")).strip() or f"SQ{index + 1:03d}",
            "label": _clean_html(child.get("question") or _record(child.get("result")).get("question") or child.get("title")),
            "order": index,
        }
        for index, child in enumerate(children)
    ]
    subquestions = [
        {
            "id": _text(child.get("qid")).strip() or None,
            "code": option["code"],
            "label": option["label"],
            "order": option["order"],
        }
        for child, option in zip(children, child_options)
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
    visibility = normalize_field_visibility(question, condition_references, issues, qid, code)
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
        elif original_type in {";", ":"}:
            columns = columns_from_children
        elif original_type == "1":
            scales = result.get("answeroptions_multiscale") or result.get("answeroptions") or question.get("answeroptions") or {}
            if isinstance(scales, list):
                scales = {str(index): scale for index, scale in enumerate(scales)}
            columns = [{"code": str(scale), "label": _clean_html(attributes.get("dualscale_headerA" if scale == 0 else "dualscale_headerB") or f"Scale {scale + 1}"),
                        "order": scale, "options": _options(_record(scales).get(str(scale)))} for scale in (0, 1)]
            if any(not column["options"] for column in columns):
                issues.append(_issue("warning", "UNSUPPORTED_TYPE", "Dual-scale question omitted: both scales must have separate answer options.",
                                     field_id=qid, question_code=code, details={"sourceType": original_type}))
                return None
        else:
            columns = options
        field["matrix"] = {
            "mode": {";": "text", ":": "number", "1": "dual-single"}.get(original_type, "single"),
            "rows": rows or child_options,
            "columns": columns,
        }
        for collection in (field["matrix"]["rows"], field["matrix"]["columns"]):
            for order, option in enumerate(collection):
                option["order"] = order
        if original_type == "1":
            field["source"]["responseAliases"] = [{
                "responseItemCode": f'{row["code"]}_{column["code"]}',
                "aliases": [f'{code}_{row["code"]}#{column["code"]}'] +
                           ([f'{survey_id}X{question["gid"]}X{qid}{row["code"]}#{column["code"]}'] if question.get("gid") else []),
            } for row in field["matrix"]["rows"] for column in columns]
        if original_type == ":" and _yes(attributes.get("multiflexible_checkbox")):
            field["matrix"]["mode"] = "multiple"
            field["responseEncoding"] = {"selectedValue": "1", "unselectedValue": "0",
                                         "selectedLabel": localized["yes"], "unselectedLabel": localized["no"]}
        elif original_type == ":":
            for native, neutral in (("multiflexible_min", "min"), ("multiflexible_max", "max")):
                limit = _validation_number(attributes.get(native), native, issues, qid, code)
                if limit is not None:
                    field.setdefault("validation", {})[neutral] = limit
            step = attributes.get("multiflexible_step")
            if step is not None and _text(step).strip() not in {"", "1"}:
                issues.append(_issue("warning", "INVALID_VALIDATION", "Numeric matrix cell increments are preserved in the source but are not enforced by the portable renderer.",
                                     field_id=qid, question_code=code, details={"rule": "multiflexible_step", "sourceValue": step}))
    return _compact(field)


def _native_validation(attributes: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Retain LimeSurvey-only validation text without treating it as portable behavior.

    Fixed numeric limits are also normalized into ``field.validation`` when the
    semantic field type supports them. Original expressions remain here so an
    importer report, diagnostic tool or future exporter can explain their
    source without forcing neutral consumers to understand ExpressionScript.
    """
    values = _compact({
        "minimumCellValueExpression": _text(attributes.get("multiflexible_min")).strip() or None,
        "maximumCellValueExpression": _text(attributes.get("multiflexible_max")).strip() or None,
        "cellStepExpression": _text(attributes.get("multiflexible_step")).strip() or None,
        "minimumAnswersExpression": _text(attributes.get("min_answers")).strip() or None,
        "maximumAnswersExpression": _text(attributes.get("max_answers")).strip() or None,
        "questionValidationExpression": _text(attributes.get("em_validation_q")).strip() or None,
        "subquestionValidationExpression": _text(attributes.get("em_validation_sq")).strip() or None,
    })
    return values or None


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
