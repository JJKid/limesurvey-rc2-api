"""Synthetic identifier families and lexical boundaries, not survey-specific ids."""

import pytest
from services.survey_structure.condition_parser import parse_limesurvey_condition
from services.survey_structure.condition_references import build_condition_references, UnsupportedConditionError


def test_all_aliases_resolve_to_the_actual_parent_and_child():
    questions = [
        {"qid": "10", "gid": "5", "title": "QUESTION_1"},
        {"qid": "20", "parent_qid": "10", "title": "ITEM_1"},
    ]
    references = build_condition_references(questions, "100")
    for alias in ("10", "Q10", "QUESTION_1", "100X5X10"):
        assert references[alias] == ("QUESTION_1", None)
    for alias in ("Q10_S20", "QUESTION_1_ITEM_1", "100X5X10ITEM_1"):
        assert references[alias] == ("QUESTION_1", "ITEM_1")


@pytest.mark.parametrize("reverse", [False, True])
def test_ambiguous_alias_is_rejected_independently_of_input_order(reverse):
    questions = [{"qid": "10", "title": "QUESTION_1"}, {"qid": "20", "title": "Q10"}]
    references = build_condition_references(list(reversed(questions)) if reverse else questions, "100")
    with pytest.raises(UnsupportedConditionError, match="more than one"):
        parse_limesurvey_condition('Q10 == "Y"', references)


@pytest.mark.parametrize("expression", [
    'QUESTION_1 == "Y" and', 'or QUESTION_1 == "Y"',
    '(QUESTION_1 == "Y"', 'QUESTION_1 == "Y")',
    'QUESTION_1 == "unclosed', 'QUESTION_1 > Infinity',
])
def test_incomplete_conditions_do_not_become_valid_rules(expression):
    with pytest.raises(UnsupportedConditionError):
        parse_limesurvey_condition(expression, {"QUESTION_1": ("QUESTION_1", None)})


def test_nested_logical_tokens_and_quoted_operators_do_not_change_grouping():
    condition = parse_limesurvey_condition(
        '(QUESTION_1 == "and or" or QUESTION_1 == "Y") and (QUESTION_1 != "N" or 1)',
        {"QUESTION_1": ("QUESTION_1", None)},
    )
    assert condition["type"] == "all"
    assert [child["type"] for child in condition["conditions"]] == ["any", "any"]
    assert condition["conditions"][0]["conditions"][0]["value"] == "and or"
    assert condition["conditions"][1]["conditions"][1] == {"type": "constant", "value": True}
