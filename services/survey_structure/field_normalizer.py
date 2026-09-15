"""Convert one LimeSurvey question, its options and field rules into SurveyStructure."""

from typing import Any, Dict, List, Optional
from .source_values import _clean_html, _issue, _record, _text, _number, _optional_number, _yes, _compact
from .field_values import (_native_validation, _validation, _validation_number, _options,
                           _localized_fixed_labels, _date_value_type, _date_order, _default_value)
from .visibility_normalizer import normalize_field_visibility
from .response_encoding import selection_encoding


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
    native_validation = _native_validation(attributes)
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
                "questionRelevanceExpression": _text(question.get("relevance")).strip() or None,
                "questionAndGroupRelevanceExpression": _text(question.get("full_condition")).strip() or None,
                "dateTimeFormat": _text(attributes.get("date_time_format")).strip() or None,
                "nativeValidation": native_validation,
            })] if any(question.get(key) not in {None, ""} for key in (
                "relevance", "full_condition"
            )) or attributes.get("date_time_format") not in {None, ""} or native_validation else None),
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
        field["responseEncoding"] = selection_encoding("Y", "N", localized)

    if field_type in {"yes-no", "gender", "single-choice", "list-with-comment", "multiple-choice", "multiple-choice-with-comments", "ranking"}:
        field["options"] = options
        if field_type == "ranking":
            field["source"]["responseAliases"] = [{
                "responseItemCode": str(index + 1),
                "aliases": [f'{code}{index + 1}', f'{label} [Rank {index + 1}]'] +
                           ([f'{survey_id}X{group_id}X{qid}{index + 1}'] if group_id else []),
            } for index in range(len(options))]
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
                           ([f'{survey_id}X{question["gid"]}X{qid}{row["code"]}#{column["code"]}'] if question.get("gid") else []) +
                           ([f'{label} [{row["label"]}][Scale {int(column["code"]) + 1}]'] if language.startswith('en') else []),
            } for row in field["matrix"]["rows"] for column in columns]
        if original_type == ":" and _yes(attributes.get("multiflexible_checkbox")):
            field["matrix"]["mode"] = "multiple"
            field["responseEncoding"] = selection_encoding("1", "0", localized)
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
