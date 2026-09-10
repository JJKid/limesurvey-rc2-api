from pathlib import Path
import json
import subprocess

import pytest

from services.survey_structure.contract import (
    SCHEMA_DIRECTORY,
    VALIDATOR_PATH,
    SurveyStructureContractError,
    validate_survey_structure,
    validate_survey_load_result,
)

CASES_PATH = Path(__file__).resolve().parent.parent / "schemas" / "validation-cases.json"


@pytest.mark.parametrize("example", json.loads(CASES_PATH.read_text()), ids=lambda case: case["name"])
def test_complete_contract_matches_shared_zod_cases(example):
    validate = validate_survey_structure if example["contract"] == "SurveyStructure" else validate_survey_load_result
    if example["valid"]:
        assert validate(example["value"]) is example["value"]
    else:
        with pytest.raises(SurveyStructureContractError):
            validate(example["value"])


def test_generated_contract_artifact_is_available_to_fastapi():
    schema_directory = Path(__file__).resolve().parent.parent / "schemas"
    assert SCHEMA_DIRECTORY == schema_directory
    assert VALIDATOR_PATH.is_file()
    assert (schema_directory / "survey-structure.schema.json").is_file()
    assert (schema_directory / "survey-load-result.schema.json").is_file()


@pytest.mark.parametrize("failure", [FileNotFoundError(), subprocess.TimeoutExpired("node", 5)])
def test_complete_validator_failure_never_accepts_unchecked_data(monkeypatch, failure):
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr("services.survey_structure.contract.subprocess.run", fail)
    with pytest.raises(RuntimeError, match="unavailable"):
        validate_survey_structure({"contractVersion": "2.0.0", "id": "test", "fields": []})


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
