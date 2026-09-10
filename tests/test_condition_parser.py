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


def test_countifop_that_selected_values_becomes_a_neutral_selection_count():
    references = {"QUESTION_1": ("QUESTION_1", None)}
    condition = parse_limesurvey_condition(
        'countifop("==", "Y", that.QUESTION_1.NAOK) >= 2',
        references,
    )
    assert condition == {
        "type": "selection-count",
        "reference": {"fieldCode": "QUESTION_1"},
        "operator": "greater-than-or-equal",
        "value": 2,
    }


def test_count_self_uses_the_current_field_code():
    references = {"QUESTION_1": ("QUESTION_1", None)}
    condition = parse_limesurvey_condition(
        "count(self.NAOK) > 0",
        references,
        current_field_code="QUESTION_1",
    )
    assert condition["reference"] == {"fieldCode": "QUESTION_1"}


def test_code_suffix_compares_the_canonical_stored_value():
    references = {"QUESTION_1": ("QUESTION_1", None)}
    condition = parse_limesurvey_condition(
        'QUESTION_1.code == "A1"',
        references,
    )
    assert condition == {
        "type": "comparison",
        "reference": {"fieldCode": "QUESTION_1"},
        "operator": "equals",
        "value": "A1",
    }
