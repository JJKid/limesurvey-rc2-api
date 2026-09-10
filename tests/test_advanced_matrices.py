"""Synthetic records match the documented LSS and RC2 scale layout; no live server is used."""
import pytest
from services.survey_structure import build_survey_structure, survey_structure_from_lss


@pytest.mark.parametrize("native,mode", [(":", "number"), ("1", "dual-single")])
def test_matrix_axes_and_separate_scales(native, mode):
    source = {
        "survey": {"sid": "900100", "language": "es"},
        "questions": [
            {"qid": "10", "parent_qid": "0", "title": "QUESTION_1", "type": native,
             "question": "Pregunta matriz", "result": {"answeroptions": {
                 "0": {"A1": {"answer": "Opción escala 1"}},
                 "1": {"A1": {"answer": "Opción escala 2"}},
             }}},
            {"qid": "11", "parent_qid": "10", "title": "R1", "question": "Fila 1", "scale_id": "0"},
            *([{"qid": "12", "parent_qid": "10", "title": "C1", "question": "Columna 1", "scale_id": "1"}] if native == ":" else []),
        ],
    }
    matrix = build_survey_structure(source)["survey"]["fields"][0]["matrix"]
    assert matrix["mode"] == mode
    assert matrix["rows"][0]["code"] == "R1"
    if native == "1":
        assert [column["options"][0]["label"] for column in matrix["columns"]] == ["Opción escala 1", "Opción escala 2"]
    else:
        assert matrix["columns"][0]["code"] == "C1"


def test_lss_does_not_overwrite_duplicate_codes_from_different_scales():
    xml = b'''<?xml version="1.0"?><document><LimeSurveyDocType>Survey</LimeSurveyDocType><DBVersion>708</DBVersion>
    <surveys><rows><row><sid>900100</sid><language>es</language></row></rows></surveys>
    <surveys_languagesettings><rows><row><surveyls_survey_id>900100</surveyls_survey_id><surveyls_language>es</surveyls_language><surveyls_title>Pregunta matriz</surveyls_title></row></rows></surveys_languagesettings>
    <questions><rows><row><qid>10</qid><sid>900100</sid><parent_qid>0</parent_qid><type>1</type><title>QUESTION_1</title><question>Pregunta matriz</question><language>es</language></row></rows></questions>
    <subquestions><rows><row><qid>11</qid><parent_qid>10</parent_qid><title>R1</title><question>Fila 1</question><language>es</language></row></rows></subquestions>
    <answers><rows>
    <row><qid>10</qid><code>A1</code><answer>Escala 1</answer><scale_id>0</scale_id><language>es</language></row>
    <row><qid>10</qid><code>A1</code><answer>Escala 2</answer><scale_id>1</scale_id><language>es</language></row>
    </rows></answers></document>'''
    matrix = survey_structure_from_lss(xml)["survey"]["fields"][0]["matrix"]
    assert [column["options"][0]["label"] for column in matrix["columns"]] == ["Escala 1", "Escala 2"]
