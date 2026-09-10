"""Runtime validation for shared survey contract values produced by Python."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict

SCHEMA_DIRECTORY = Path(__file__).resolve().parents[2] / "schemas"
VALIDATOR_PATH = SCHEMA_DIRECTORY / "validate-survey.cjs"
MAX_DOCUMENT_BYTES = 16 * 1024 * 1024
VALIDATION_TIMEOUT_SECONDS = 5


class SurveyStructureContractError(RuntimeError):
    """FastAPI produced a value that violates the shared SurveyStructure contract."""

    def __init__(self, message: str, errors: list | None = None):
        super().__init__(message)
        self.errors = errors or []


def validate_survey_structure(value: Dict[str, Any]) -> Dict[str, Any]:
    """Validate structure and all Zod refinements with the generated local validator."""
    return _validate_complete_contract("SurveyStructure", value)


def validate_survey_load_result(value: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an import/load result and return it unchanged when valid."""
    return _validate_complete_contract("SurveyLoadResult", value)


def _validate_complete_contract(contract_name: str, value: Dict[str, Any]) -> Dict[str, Any]:
    # JSON Schema remains the portable description; the bundled Zod code is
    # authoritative for cross-field rules. Never silently fall back to schema-only.
    try:
        payload = json.dumps({"contract": contract_name, "value": value}, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SurveyStructureContractError("Survey contract document must contain only JSON values.") from error
    if len(payload) > MAX_DOCUMENT_BYTES:
        raise SurveyStructureContractError("Survey contract document exceeds the validation size limit.")
    try:
        completed = subprocess.run(
            ["node", str(VALIDATOR_PATH)], input=payload, capture_output=True,
            timeout=VALIDATION_TIMEOUT_SECONDS, check=True,
        )
        result = json.loads(completed.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise RuntimeError("The complete survey contract validator is unavailable.") from error
    if result.get("success") is True:
        return value
    errors = result.get("issues")
    if not isinstance(errors, list) or not errors:
        raise RuntimeError("The complete survey contract validator returned an invalid result.")
    first = errors[0]
    path = ".".join(str(part) for part in first.get("path", [])) or "<root>"
    raise SurveyStructureContractError(
        f"{contract_name} output violates the shared contract at {path}: {first['message']}", errors,
    )
