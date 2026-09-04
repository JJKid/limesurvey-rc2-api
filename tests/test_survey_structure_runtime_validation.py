from pathlib import Path

import pytest

from services.survey_structure.contract import (
    SCHEMA_PATHS,
    SurveyStructureContractError,
    validate_survey_structure,
)


def test_generated_contract_artifact_is_available_to_fastapi():
    schema_directory = Path(__file__).resolve().parent.parent / "schemas"
    assert SCHEMA_PATHS["SurveyStructure"] == schema_directory / "survey-structure.schema.json"
    assert SCHEMA_PATHS["SurveyLoadResult"] == schema_directory / "survey-load-result.schema.json"
    assert all(path.is_file() for path in SCHEMA_PATHS.values())


def test_python_output_is_validated_against_the_shared_contract():
    valid = {
        "contractVersion": "2.0.0",
        "id": "123",
        "fields": [{"id": "1", "code": "Q1", "type": "short-text", "label": "Name"}],
    }
    assert validate_survey_structure(valid) is valid


def test_misspelled_python_output_property_is_rejected():
    invalid = {
        "contractVersion": "2.0.0",
        "id": "123",
        "fields": [{
            "id": "1",
            "code": "Q1",
            "type": "short-text",
            "label": "Name",
            "renderign": {"widget": "text-input"},
        }],
    }
    with pytest.raises(SurveyStructureContractError, match="renderign"):
        validate_survey_structure(invalid)
