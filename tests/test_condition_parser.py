from services.survey_structure.condition_parser import parse_limesurvey_condition


def test_count_that_expression_becomes_a_neutral_selection_count():
    references = {"QUESTION_1": ("QUESTION_1", None)}
    assert parse_limesurvey_condition(
        "count(that.QUESTION_1.NAOK) >= 2",
        references,
    ) == {
        "type": "selection-count",
        "reference": {"fieldCode": "QUESTION_1"},
        "operator": "greater-than-or-equal",
        "value": 2,
    }


def test_countif_that_expression_uses_the_same_neutral_condition():
    references = {"QUESTION_1": ("QUESTION_1", None)}
    condition = parse_limesurvey_condition(
        'countif("Y", that.QUESTION_1.NAOK) == 1',
        references,
    )
    assert condition["type"] == "selection-count"
    assert condition["value"] == 1
