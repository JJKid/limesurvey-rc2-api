"""Read field options, typed validation limits and default/date values."""
import re
from typing import Any, Dict, List, Optional
from .source_values import _clean_html, _issue, _record, _text, _number, _optional_number, _yes, _compact

def _native_validation(attributes: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Retain LimeSurvey-only validation text without treating it as portable behavior.

    Fixed numeric limits are also normalized into ``field.validation`` when the
    semantic field type supports them. Original expressions remain here so an
    importer report, diagnostic tool or future exporter can explain their
    source without forcing neutral consumers to understand ExpressionScript.
    """
    values = _compact({
        "minimumNumericValueExpression": _text(attributes.get("min_num_value")).strip() or None,
        "maximumNumericValueExpression": _text(attributes.get("max_num_value")).strip() or None,
        "minimumAnswerExpression": _text(attributes.get("minimum_answer")).strip() or None,
        "maximumAnswerExpression": _text(attributes.get("maximum_answer")).strip() or None,
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
    numeric_limits = {rule: _validation_number(attributes.get(rule), rule, issues, field_id, question_code)
                      for rule in ("min_num_value", "minimum_answer", "max_num_value", "maximum_answer",
                                   "min_answers", "max_answers")}
    if field_type in {"number", "range"}:
        for portable, rules in (("min", ("min_num_value", "minimum_answer")),
                                ("max", ("max_num_value", "maximum_answer"))):
            for rule in rules:
                value = attributes.get(rule)
                if value is not None and _text(value).strip():
                    validation[portable] = numeric_limits[rule]
                    break
        validation["integer"] = (
            _yes(attributes.get("num_value_int_only"))
            if attributes.get("num_value_int_only") is not None else None
        )
    if field_type in {"multiple-choice", "multiple-choice-with-comments", "ranking"}:
        validation.update({
            "minSelections": numeric_limits["min_answers"],
            "maxSelections": numeric_limits["max_answers"],
        })
    for rule in ("em_validation_q", "em_validation_sq"):
        value = attributes.get(rule)
        if value is not None and _text(value).strip():
            issues.append(_issue(
                "warning", "INVALID_VALIDATION",
                f"Question {question_code} retains {rule} in its source, but the portable renderer does not enforce this native validation expression.",
                field_id=field_id, question_code=question_code,
                details={"rule": rule, "sourceValue": value},
            ))
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


def _date_format_tokens(source_format: Any) -> List[tuple[str, int]]:
    """Distinguish calendar months from minutes following hours/before seconds."""
    value = re.sub(r"'[^']*'|\"[^\"]*\"", lambda match: " " * len(match.group()), _text(source_format))
    tokens = [(match.group()[0].lower(), match.start()) for match in re.finditer(r"([dmyhis])\1*", value, re.IGNORECASE)]
    return [("i" if kind == "m" and (
        (index > 0 and tokens[index - 1][0] == "h")
        or (index + 1 < len(tokens) and tokens[index + 1][0] == "s")
    ) else kind, position) for index, (kind, position) in enumerate(tokens)]


def _date_value_type(source_format: Any) -> str:
    """Map a LimeSurvey date/time display format to its portable stored-value type."""
    kinds = {kind for kind, _ in _date_format_tokens(source_format)}
    has_day, has_month, has_year, has_time = (kind in kinds for kind in ("d", "m", "y", "h"))
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
    if _date_value_type(source_format) != "date-time":
        return None
    tokens = _date_format_tokens(source_format)
    first_time = next(position for kind, position in tokens if kind == "h")
    date_positions = [position for kind, position in tokens if kind in {"d", "m", "y"}]
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
