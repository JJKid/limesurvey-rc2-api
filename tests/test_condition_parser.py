from services.survey_structure.condition_parser import parse_limesurvey_condition
from services.survey_structure.condition_references import build_condition_references, UnsupportedConditionError
import pytest


def test_count_that_expression_becomes_a_neutral_selection_count():
    references = {"QUESTION_1": ("QUESTION_1", None)}
    assert parse_limesurvey_condition(
        "count(that.QUESTION_1.NAOK) >= 2",
        references,
    ) == {
        "type": "selection-count",
        "responseReference": {"fieldCode": "QUESTION_1"},
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
        "responseReference": {"fieldCode": "QUESTION_1"},
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
    assert condition["responseReference"] == {"fieldCode": "QUESTION_1"}


def test_code_suffix_compares_the_canonical_stored_value():
    references = {"QUESTION_1": ("QUESTION_1", None)}
    condition = parse_limesurvey_condition(
        'QUESTION_1.code == "A1"',
        references,
    )
    assert condition == {
        "type": "comparison",
        "responseReference": {"fieldCode": "QUESTION_1"},
        "operator": "equals",
        "value": "A1",
    }


@pytest.mark.parametrize('native', ['Q', ';', ':', 'F', '1'])
def test_count_answered_inputs_and_matrix_cells_is_not_selection_count(native):
    references = build_condition_references([{'qid': '10', 'title': 'QUESTION_1', 'type': native}], '100')
    condition = parse_limesurvey_condition('count(that.QUESTION_1.NAOK) >= 2', references)
    assert condition['type'] == 'answered-count'


def test_comments_are_not_silently_discarded_from_count():
    references = build_condition_references([{'qid': '10', 'title': 'QUESTION_1', 'type': 'P'}], '100')
    with pytest.raises(UnsupportedConditionError, match='cannot be counted faithfully'):
        parse_limesurvey_condition('count(that.QUESTION_1.NAOK) >= 2', references)
    assert parse_limesurvey_condition('count(that.QUESTION_1.nocomments.NAOK) >= 2', references)['type'] == 'selection-count'
    assert parse_limesurvey_condition('count(self.nocomments.NAOK) >= 2', references, 'QUESTION_1')['type'] == 'selection-count'


def test_this_requires_a_known_scalar_context():
    references = build_condition_references([{'qid': '10', 'title': 'QUESTION_1', 'type': 'N'}], '100')
    assert parse_limesurvey_condition('this.NAOK >= 18', references, 'QUESTION_1')['responseReference'] == {'fieldCode': 'QUESTION_1'}
    with pytest.raises(UnsupportedConditionError, match='current scalar'):
        parse_limesurvey_condition('this.NAOK >= 18', references)


def test_this_does_not_guess_a_matrix_cell():
    references = build_condition_references([{'qid': '10', 'title': 'QUESTION_1', 'type': ':'}], '100')
    with pytest.raises(UnsupportedConditionError, match='specific response cell'):
        parse_limesurvey_condition('this.NAOK >= 18', references, 'QUESTION_1')
