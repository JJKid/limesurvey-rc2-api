"""Format and validation cases independent from production survey IDs."""

import pytest

from services.survey_structure.field_values import _date_order, _date_value_type
from services.survey_structure.field_normalizer import normalize_field
from services.survey_structure import build_survey_structure


@pytest.mark.parametrize(("source_format", "value_type", "date_order"), [
    ("HH:mm", "time", None),
    ("HH:mm:ss", "time", None),
    ("hh:MM", "time", None),
    ("dd-mm-yyyy", "date", None),
    ("mm/yyyy", "month-year", None),
    ("yyyy", "year", None),
    ("yyyy-mm-dd HH:mm", "date-time", "date-time"),
    ("HH:mm yyyy-mm-dd", "date-time", "time-date"),
    ("HH:mm 'day'", "time", None),
])
def test_date_format_tokens_distinguish_clock_minutes_from_calendar_months(source_format, value_type, date_order):
    assert _date_value_type(source_format) == value_type
    assert _date_order(source_format) == date_order


@pytest.mark.parametrize(("rule", "native_name", "portable_name"), [
    ("min_num_value", "minimumNumericValueExpression", "min"),
    ("max_num_value", "maximumNumericValueExpression", "max"),
    ("minimum_answer", "minimumAnswerExpression", "min"),
    ("maximum_answer", "maximumAnswerExpression", "max"),
])
def test_dynamic_numeric_limit_is_retained_and_explicitly_not_enforced(rule, native_name, portable_name):
    issues = []
    value = "LIMIT.NAOK + 1"
    field = normalize_field({
        "qid": "synthetic-question", "title": "AMOUNT", "type": "N", "question": "Amount",
        "result": {"attributes": {rule: value}},
    }, [], "synthetic-survey", "en", issues, {})
    assert portable_name not in field.get("validation", {})
    assert field["source"]["extensions"][0]["nativeValidation"][native_name] == value
    assert any(issue["code"] == "INVALID_VALIDATION" and issue["details"] == {"rule": rule, "sourceValue": value}
               for issue in issues)


@pytest.mark.parametrize("rule", ["em_validation_q", "em_validation_sq"])
def test_native_expression_has_a_warning_that_preservation_is_not_execution(rule):
    issues = []
    field = normalize_field({
        "qid": "synthetic-question", "title": "AMOUNT", "type": "N", "question": "Amount",
        "result": {"attributes": {rule: "self.NAOK > 0"}},
    }, [], "synthetic-survey", "en", issues, {})
    assert field["source"]["extensions"][0]["nativeValidation"]
    assert any(issue["code"] == "INVALID_VALIDATION" and issue["details"]["rule"] == rule for issue in issues)


def test_numeric_zero_has_priority_over_legacy_alias_and_dynamic_alias_is_still_diagnosed():
    issues = []
    field = normalize_field({
        "qid": "synthetic-question", "title": "AMOUNT", "type": "N", "question": "Amount",
        "result": {"attributes": {"min_num_value": 0, "minimum_answer": "LIMIT.NAOK"}},
    }, [], "synthetic-survey", "en", issues, {})
    assert field["validation"]["min"] == 0
    native = field["source"]["extensions"][0]["nativeValidation"]
    assert native["minimumNumericValueExpression"] == "0"
    assert native["minimumAnswerExpression"] == "LIMIT.NAOK"
    assert any(issue["details"]["rule"] == "minimum_answer" for issue in issues)


def test_dynamic_validation_round_trip_satisfies_the_packaged_shared_contract():
    rules = {rule: "LIMIT.NAOK + 1" for rule in (
        "min_num_value", "max_num_value", "minimum_answer", "maximum_answer",
    )}
    result = build_survey_structure({
        "survey": {"sid": "synthetic-survey", "language": "en"},
        "questions": [{
            "qid": "synthetic-question", "parent_qid": "0", "title": "AMOUNT", "type": "N",
            "question": "Amount", "result": {"attributes": rules},
        }],
    })
    field = result["survey"]["fields"][0]
    assert "validation" not in field
    assert len(field["source"]["extensions"][0]["nativeValidation"]) == len(rules)
    assert {issue["details"]["rule"] for issue in result["issues"] if issue["code"] == "INVALID_VALIDATION"} == set(rules)
