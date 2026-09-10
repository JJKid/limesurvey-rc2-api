"""Normalize field visibility and report unsupported syntax without executing it."""

import logging
import re
from typing import Any, Dict, List, Optional
from .condition_parser import UnsupportedConditionError, parse_limesurvey_condition
from .source_values import _issue, _text

logger = logging.getLogger("uvicorn.error")


def normalize_field_visibility(
    question: Dict[str, Any],
    condition_references: Dict[str, tuple[str, Optional[str]]],
    issues: List[Dict[str, Any]],
    field_id: str,
    question_code: str,
) -> Dict[str, Any]:
    full = _text(question.get("full_condition")).strip()
    relevance = _text(question.get("relevance")).strip()
    legacy_condition = _text(question.get("condition")).strip()
    # Group relevance is represented once on SurveyStructure.groups. Formly
    # combines it with this field-level condition when producing the runtime
    # projection, so it must not be copied into every field here.
    expression = next((candidate for candidate in (
        relevance,
        legacy_condition,
        full,
    ) if candidate and candidate != "1"), "")
    if not expression:
        return {}
    try:
        condition = parse_limesurvey_condition(
            expression,
            condition_references,
            current_field_code=question_code,
        )
        return {"condition": condition} if condition else {}
    except UnsupportedConditionError as error:
        log_unsupported_condition(expression, scope="field", owner=question_code)
        issues.append(_issue(
            "warning", "INVALID_EXPRESSION", str(error),
            field_id=field_id, question_code=question_code,
            details={"sourceExpression": expression},
        ))
        return {}


def log_unsupported_condition(expression: str, scope: str, owner: str) -> None:
    """Record the unsupported syntax family without logging survey answer data."""
    function_match = re.search(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(", expression)
    suffixes = sorted(set(re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)", expression)))
    logger.warning(
        "unsupported_expression_script scope=%s owner=%s function=%s suffixes=%s",
        scope,
        owner,
        function_match.group(1).lower() if function_match else "none",
        ",".join(suffix.lower() for suffix in suffixes) or "none",
    )
