"""Runtime validation for shared survey contract values produced by Python."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

from jsonschema import Draft7Validator


SCHEMA_DIRECTORY = Path(__file__).resolve().parents[2] / "schemas"
SCHEMA_PATHS = {
    "SurveyStructure": SCHEMA_DIRECTORY / "survey-structure.schema.json",
    "SurveyLoadResult": SCHEMA_DIRECTORY / "survey-load-result.schema.json",
}


class SurveyStructureContractError(RuntimeError):
    """FastAPI produced a value that violates the shared SurveyStructure contract."""


@lru_cache(maxsize=len(SCHEMA_PATHS))
def _contract_validator(contract_name: str) -> Draft7Validator:
    """Load and compile one generated JSON Schema once per process."""
    schema_path = SCHEMA_PATHS[contract_name]
    with schema_path.open("r", encoding="utf-8") as schema_file:
        schema = json.load(schema_file)
    Draft7Validator.check_schema(schema)
    return Draft7Validator(schema)


def validate_survey_structure(value: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a survey definition against the generated shared JSON Schema.

    Return the same object when valid. Otherwise report the first failing path.
    """
    errors = sorted(
        _contract_validator("SurveyStructure").iter_errors(value),
        key=lambda error: list(error.path),
    )
    if not errors:
        return value

    error = errors[0]
    path = ".".join(str(part) for part in error.absolute_path) or "<root>"
    raise SurveyStructureContractError(
        f"SurveyStructure output violates the shared contract at {path}: {error.message}"
    )


def validate_survey_load_result(value: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an import/load result and return it unchanged when valid."""
    errors = sorted(
        _contract_validator("SurveyLoadResult").iter_errors(value),
        key=lambda error: list(error.path),
    )
    if not errors:
        return value

    error = errors[0]
    path = ".".join(str(part) for part in error.absolute_path) or "<root>"
    raise SurveyStructureContractError(
        f"SurveyLoadResult output violates the shared contract at {path}: {error.message}"
    )
