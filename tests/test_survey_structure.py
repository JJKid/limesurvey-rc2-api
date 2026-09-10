import json
from pathlib import Path

import pytest

from services.survey_structure import (
    SurveyStructureSourceError,
    build_survey_structure,
    survey_structure_from_lss,
)


FIXTURE_DIRECTORY = Path(__file__).parent / "fixtures"
GOLDEN_DIRECTORY = FIXTURE_DIRECTORY / "golden"
LSS_FIXTURES = tuple(sorted(FIXTURE_DIRECTORY.glob("*.lss")))
EXAMPLE_DIRECTORY = Path(__file__).parents[1] / "examples"


@pytest.mark.parametrize("path", LSS_FIXTURES, ids=lambda path: path.stem)
def test_supported_lss_fixtures_produce_survey_structure(path):
    load_result = survey_structure_from_lss(path.read_bytes())
    survey = load_result["survey"]
    assert survey["contractVersion"] == "2.0.0"
    assert survey["id"]
    extension = survey["source"]["extensions"][0]
    assert extension["type"] == "limesurvey-survey"
    assert extension["databaseSchemaVersion"] in {"348", "623", "643", "708"}
    assert survey["fields"]


@pytest.mark.parametrize("path", LSS_FIXTURES, ids=lambda path: f"golden-{path.stem}")
def test_lss_fixture_matches_complete_golden_result(path):
    expected_path = (
        FIXTURE_DIRECTORY / "survey_load_result_783587.json"
        if path.stem == "limesurvey_survey_783587"
        else GOLDEN_DIRECTORY / f"{path.stem}.json"
    )
    expected = json.loads(expected_path.read_text(encoding="utf-8"))

    assert survey_structure_from_lss(path.read_bytes()) == expected


def test_remotecontrol_payload_produces_same_contract_shape():
    load_result = build_survey_structure({
        "survey": {"sid": "123", "language": "es", "format": "G"},
        "language": {"surveyls_title": "Encuesta"},
        "groups": [{"gid": "10", "group_name": "General", "group_order": "1"}],
        "questions": [{
            "qid": "100", "gid": "10", "parent_qid": "0", "title": "Q1",
            "type": "L", "question": "Pregunta", "mandatory": "Y",
            "result": {"answeroptions": {"A1": {"answer": "Sí"}}},
        }],
    })
    assert load_result["survey"]["fields"][0] == {
        "id": "100", "code": "Q1", "type": "single-choice", "label": "Pregunta",
        "required": True, "order": 0, "groupId": "10",
        "options": [{"code": "A1", "label": "Sí", "order": 0}],
        "source": {
            "platform": "limesurvey", "surveyId": "123", "groupId": "10",
            "questionId": "100", "nativeType": "L",
        },
    }


def test_lss_rejects_dtd_and_unknown_database_schema():
    with pytest.raises(SurveyStructureSourceError, match="DTD"):
        survey_structure_from_lss(b'<!DOCTYPE foo><document/>')
    with pytest.raises(SurveyStructureSourceError, match="Unsupported LSS DBVersion"):
        survey_structure_from_lss(
            b'<document><LimeSurveyDocType>Survey</LimeSurveyDocType><DBVersion>999</DBVersion>'
            b'<surveys><rows><row><sid>1</sid></row></rows></surveys></document>'
        )


def test_html_is_reduced_to_visible_plain_text_without_scripts_or_styles():
    load_result = build_survey_structure({
        "survey": {"sid": "123", "language": "es"},
        "language": {"surveyls_title": "<b>Encuesta</b><script>alert(1)</script>"},
        "questions": [{
            "qid": "100", "parent_qid": "0", "title": "Q1", "type": "S",
            "question": "<p>Nombre<br>completo</p><style>body{display:none}</style>",
            "help": "<strong>Sin abreviaturas</strong>",
        }],
    })

    assert load_result["survey"]["title"] == "Encuesta"
    field = load_result["survey"]["fields"][0]
    assert field["label"] == "Nombre\ncompleto"
    assert field["help"] == "Sin abreviaturas"


def test_synthetic_display_question_lss_maps_x_without_a_response_field():
    result = survey_structure_from_lss(
        (EXAMPLE_DIRECTORY / "display-message-question.lss").read_bytes()
    )

    assert result["issues"] == []
    assert result["survey"]["fields"] == [{
        "id": "100",
        "code": "QUESTION_1",
        "type": "display",
        "label": "Pregunta de encuesta 1: texto informativo que no espera una respuesta.",
        "required": False,
        "order": 0,
        "source": {
            "platform": "limesurvey",
            "surveyId": "900008",
            "groupId": "10",
            "questionId": "100",
            "nativeType": "X",
            "extensions": [{
                "type": "limesurvey-question",
                "version": "1.0.0",
                "relevanceExpression": "1",
            }],
        },
        "groupId": "10",
    }]


def test_synthetic_selection_count_lss_uses_generic_codes_and_portable_condition():
    result = survey_structure_from_lss(
        (EXAMPLE_DIRECTORY / "visibility-at-least-two-selections.lss").read_bytes()
    )

    fields = {field["code"]: field for field in result["survey"]["fields"]}
    assert [option["code"] for option in fields["QUESTION_1"]["options"]] == [
        "RESPONSE_OPTION_1", "RESPONSE_OPTION_2", "RESPONSE_OPTION_3",
    ]
    assert fields["QUESTION_2"]["visibility"]["condition"] == {
        "type": "selection-count",
        "reference": {"fieldCode": "QUESTION_1"},
        "operator": "greater-than-or-equal",
        "value": 2,
    }


def test_synthetic_dynamic_validation_lss_uses_generic_source_reference():
    result = survey_structure_from_lss(
        (EXAMPLE_DIRECTORY / "warning-dynamic-validation.lss").read_bytes()
    )

    fields = {field["code"]: field for field in result["survey"]["fields"]}
    assert fields["QUESTION_1"]["type"] == "number"
    assert fields["QUESTION_2"]["type"] == "multiple-choice"
    issue = next(item for item in result["issues"] if item["code"] == "INVALID_VALIDATION")
    assert issue["questionCode"] == "QUESTION_2"
    assert issue["details"] == {
        "rule": "min_answers",
        "sourceValue": "QUESTION_1.NAOK",
    }


def test_builder_preserves_source_expression_and_emits_portable_condition():
    load_result = build_survey_structure({
        "survey": {"sid": "900001", "language": "es"},
        "groups": [{"gid": "10", "group_name": "Synthetic group", "group_order": "0"}],
        "questions": [
            {
                "qid": "100", "gid": "10", "parent_qid": "0", "title": "SOURCE",
                "type": "L", "question": "Source question",
                "result": {"answeroptions": {"A1": {"answer": "First option"}}},
            },
            {
                "qid": "200", "gid": "10", "parent_qid": "0", "title": "FOLLOW_UP",
                "type": "S", "question": "Follow-up question",
                "relevance": '900001X10X100.NAOK == "A1"',
            },
        ],
    })
    field = next(item for item in load_result["survey"]["fields"] if item["code"] == "FOLLOW_UP")
    extension = next(
        item for item in field["source"]["extensions"]
        if item["type"] == "limesurvey-question"
    )
    assert extension["relevanceExpression"] == '900001X10X100.NAOK == "A1"'
    assert field["visibility"] == {
        "condition": {
            "type": "comparison",
            "reference": {"fieldCode": "SOURCE"},
            "operator": "equals",
            "value": "A1",
        }
    }


def test_builder_keeps_group_and_question_visibility_as_separate_neutral_rules():
    load_result = build_survey_structure({
        "survey": {"sid": "900002", "language": "es"},
        "groups": [{
            "gid": "10", "group_name": "Conditional group", "group_order": "0",
            "grelevance": 'CONSENT.NAOK == "Y"',
        }],
        "questions": [
            {
                "qid": "100", "gid": "10", "parent_qid": "0", "title": "CONSENT",
                "type": "Y", "question": "Consent",
            },
            {
                "qid": "200", "gid": "10", "parent_qid": "0", "title": "AGE",
                "type": "N", "question": "Age",
            },
            {
                "qid": "300", "gid": "10", "parent_qid": "0", "title": "FOLLOW_UP",
                "type": "S", "question": "Follow up",
                "relevance": "AGE.NAOK >= 18",
                "full_condition": '((CONSENT.NAOK == "Y") AND (AGE.NAOK >= 18))',
            },
        ],
    })
    survey = load_result["survey"]
    assert survey["groups"][0]["visibility"]["condition"]["reference"]["fieldCode"] == "CONSENT"
    follow_up = next(field for field in survey["fields"] if field["code"] == "FOLLOW_UP")
    assert follow_up["visibility"]["condition"] == {
        "type": "comparison",
        "reference": {"fieldCode": "AGE"},
        "operator": "greater-than-or-equal",
        "value": 18,
    }


def test_builder_normalizes_internal_child_aliases_and_type_specific_validation():
    load_result = build_survey_structure({
        "survey": {"sid": "survey-synthetic", "language": "es"},
        "groups": [{"gid": "10", "group_name": "Synthetic group", "group_order": "0"}],
        "questions": [
            {
                "qid": "100", "gid": "10", "parent_qid": "0", "title": "SERVICES",
                "type": "M", "question": "Services",
            },
            {
                "qid": "101", "gid": "10", "parent_qid": "100", "title": "OPTION_1",
                "type": "T", "question": "First service",
            },
            {
                "qid": "200", "gid": "10", "parent_qid": "0", "title": "FOLLOW_UP",
                "type": "S", "question": "Follow-up",
                "relevance": 'Q100_S101.NAOK == "Y"',
            },
            {
                "qid": "300", "gid": "10", "parent_qid": "0", "title": "ONE_CHOICE",
                "type": "L", "question": "One choice",
                "result": {
                    "answeroptions": {"A1": {"answer": "First"}},
                    "attributes": {"min_answers": "1", "max_answers": "1"},
                },
            },
        ],
    })
    fields = {field["code"]: field for field in load_result["survey"]["fields"]}
    assert "minSelections" not in fields["ONE_CHOICE"].get("validation", {})
    assert "maxSelections" not in fields["ONE_CHOICE"].get("validation", {})
    assert ("SERVICES", "OPTION_1") in _condition_references(fields["FOLLOW_UP"])


def test_dynamic_selection_limit_is_reported_without_inventing_a_number():
    load_result = build_survey_structure({
        "survey": {"sid": "survey-synthetic", "language": "es"},
        "questions": [
            {
                "qid": "100", "parent_qid": "0", "title": "SERVICES", "type": "M",
                "question": "Services", "result": {"attributes": {"min_answers": "LIMIT.NAOK"}},
            },
            {
                "qid": "101", "parent_qid": "100", "title": "OPTION_1", "type": "T",
                "question": "First service",
            },
        ],
    })
    field = load_result["survey"]["fields"][0]
    assert "minSelections" not in field.get("validation", {})
    issue = next(item for item in load_result["issues"] if item["code"] == "INVALID_VALIDATION")
    assert issue["level"] == "warning"
    assert issue["details"] == {"rule": "min_answers", "sourceValue": "LIMIT.NAOK"}
    extension = field["source"]["extensions"][0]
    assert extension["nativeValidation"] == {
        "minimumAnswersExpression": "LIMIT.NAOK",
    }


def test_relevant_limesurvey_attributes_are_normalized_or_retained_explicitly():
    result = build_survey_structure({
        "survey": {"sid": "synthetic-attributes", "language": "es"},
        "questions": [
            {
                "qid": "100", "parent_qid": "0", "title": "VISIT_DATE", "type": "D",
                "question": "Visit date", "mandatory": "Y",
                "result": {"attributes": {"date_time_format": "dd-mm-yyyy HH:MM"}},
            },
            {
                "qid": "200", "parent_qid": "0", "title": "SERVICES", "type": "P",
                "question": "Services", "other": "Y",
                "result": {"attributes": {
                    "min_answers": "1",
                    "max_answers": "2",
                    "em_validation_q": "count(self.NAOK) <= 2",
                }},
            },
            {
                "qid": "201", "parent_qid": "200", "title": "SQ001", "type": "T",
                "question": "Library", "question_order": "0", "scale_id": "0",
            },
            {
                "qid": "202", "parent_qid": "200", "title": "SQ002", "type": "T",
                "question": "Computer room", "question_order": "1", "scale_id": "0",
            },
        ],
    })
    fields = {field["code"]: field for field in result["survey"]["fields"]}

    assert fields["VISIT_DATE"]["required"] is True
    assert fields["VISIT_DATE"]["dateValueType"] == "date-time"
    assert fields["VISIT_DATE"]["rendering"] == {"dateOrder": "date-time"}
    assert fields["SERVICES"]["validation"] == {"minSelections": 1, "maxSelections": 2}
    assert [option["code"] for option in fields["SERVICES"]["options"]] == ["SQ001", "SQ002"]
    assert fields["SERVICES"]["other"] == {
        "code": "-oth-",
        "label": "Otro",
        "textResponseKey": "SERVICES_OTHER_value",
        "commentResponseKey": "SERVICES_OTHER_comment",
    }
    assert fields["SERVICES"]["source"]["extensions"][0]["nativeValidation"] == {
        "minimumAnswersExpression": "1",
        "maximumAnswersExpression": "2",
        "questionValidationExpression": "count(self.NAOK) <= 2",
    }


@pytest.mark.parametrize(
    ("native_type", "semantic_type"),
    [
        ("S", "short-text"), ("T", "long-text"), ("D", "date"),
        ("Y", "yes-no"), ("G", "gender"), ("L", "single-choice"),
        ("!", "single-choice"), ("O", "list-with-comment"),
        ("M", "multiple-choice"), ("P", "multiple-choice-with-comments"),
        ("N", "number"), ("F", "matrix"), ("H", "matrix"),
        ("B", "matrix"), (";", "matrix"), ("Q", "multiple-input"),
        ("R", "ranking"), ("X", "display"),
    ],
)
def test_each_supported_native_type_has_an_explicit_semantic_mapping(native_type, semantic_type):
    questions = [{
        "qid": "100", "gid": "10", "parent_qid": "0", "title": "Q1",
        "type": native_type, "question": "Synthetic question",
        "result": {
            "answeroptions": {
                "A1": {"answer": "First"},
                "A2": {"answer": "Second"},
            }
        },
    }]
    if native_type in {"M", "P", "Q", "F", "H", "B", ";"}:
        questions.extend([
            {
                "qid": "101", "gid": "10", "parent_qid": "100", "title": "SQ001",
                "type": "T", "question": "First row", "question_order": "0", "scale_id": "0",
            },
            {
                "qid": "102", "gid": "10", "parent_qid": "100", "title": "SQ002",
                "type": "T", "question": "Second row", "question_order": "1",
                "scale_id": "1" if native_type == ";" else "0",
            },
        ])

    result = build_survey_structure({
        "survey": {"sid": "synthetic-types", "language": "es"},
        "groups": [{"gid": "10", "group_name": "Synthetic group", "group_order": "0"}],
        "questions": questions,
    })

    assert result["survey"]["fields"][0]["type"] == semantic_type
    assert result["survey"]["fields"][0]["source"]["nativeType"] == native_type


def test_matrix_source_order_does_not_mix_row_and_column_scales():
    result = build_survey_structure({
        "survey": {"sid": "synthetic-matrix", "language": "es"},
        "questions": [
            {"qid": "1", "parent_qid": "0", "title": "Q01", "type": ";", "question": "Question"},
            {"qid": "2", "parent_qid": "1", "title": "R2", "type": "T", "question": "Row 2", "scale_id": "0", "question_order": "1"},
            {"qid": "3", "parent_qid": "1", "title": "C1", "type": "T", "question": "Column 1", "scale_id": "1", "question_order": "0"},
            {"qid": "4", "parent_qid": "1", "title": "R1", "type": "T", "question": "Row 1", "scale_id": "0", "question_order": "0"},
            {"qid": "5", "parent_qid": "1", "title": "C2", "type": "T", "question": "Column 2", "scale_id": "1", "question_order": "1"},
        ],
    })
    assert result["survey"]["fields"][0]["matrix"] == {
        "mode": "text",
        "rows": [{"code": "R1", "label": "Row 1", "order": 0}, {"code": "R2", "label": "Row 2", "order": 1}],
        "columns": [{"code": "C1", "label": "Column 1", "order": 0}, {"code": "C2", "label": "Column 2", "order": 1}],
    }


@pytest.mark.parametrize("native_type", ["A", "C", "E", "5", "K", "U", "I", "|", "*"])
def test_unimplemented_native_type_is_reported_instead_of_disappearing(native_type):
    result = build_survey_structure({
        "survey": {"sid": "synthetic-unsupported", "language": "es"},
        "questions": [{
            "qid": "100", "parent_qid": "0", "title": "Q1",
            "type": native_type, "question": "Synthetic unsupported question",
        }],
    })

    assert result["survey"]["fields"] == []
    issue = result["issues"][0]
    assert issue["code"] == "UNSUPPORTED_TYPE"
    assert issue["details"] == {"sourceType": native_type}


def test_unknown_condition_reference_becomes_an_import_warning():
    load_result = build_survey_structure({
        "survey": {"sid": "123", "language": "es"},
        "questions": [{
            "qid": "1", "parent_qid": "0", "title": "Q1", "type": "S",
            "question": "Visible conditionally", "relevance": 'MISSING.NAOK == "Y"',
        }],
    })

    field = load_result["survey"]["fields"][0]
    assert "visibility" not in field
    issue = next(item for item in load_result["issues"] if item["code"] == "INVALID_EXPRESSION")
    assert issue["level"] == "warning"
    assert issue["questionCode"] == "Q1"
    assert "MISSING" in issue["message"]


def _condition_references(field):
    references = set()

    def visit(condition):
        reference = condition.get("reference")
        if reference:
            references.add((reference["fieldCode"], reference.get("responseItemCode")))
        for child in condition.get("conditions", []):
            visit(child)
        if condition.get("condition"):
            visit(condition["condition"])

    visit(field["visibility"]["condition"])
    return references
