"""Translate the supported LimeSurvey condition subset into portable condition trees."""

from __future__ import annotations

import re
import json
import math
from typing import Any, Dict, List, Mapping, Optional, Tuple


from .condition_references import (ConditionReference, ConditionReferenceIndex, UnsupportedConditionError,
                                   build_condition_references, resolve_reference as _resolve_reference)
from .condition_tokens import split_logical as _split_logical, strip_outer_parentheses as _strip_outer_parentheses


_COMPARISON = re.compile(
    r"^([A-Za-z0-9_]+(?:X[0-9]+X[0-9]+X[0-9]+)?(?:_[A-Za-z0-9]+)*)"
    r"(?:\.(?:NAOK|code))?\s*(==|!=|>=|<=|>|<)\s*(.+)$",
    re.IGNORECASE,
)

_OPERATORS = {
    "==": "equals",
    "!=": "not-equals",
    ">": "greater-than",
    ">=": "greater-than-or-equal",
    "<": "less-than",
    "<=": "less-than-or-equal",
}

_MACRO_TARGET = r"((?:that|self)(?:\.[A-Za-z0-9_]+)*)"
_COUNT = re.compile(
    rf"^count\s*\(\s*{_MACRO_TARGET}\s*\)\s*(==|!=|>=|<=|>|<)\s*([0-9]+)$",
    re.IGNORECASE,
)
_COUNTIF = re.compile(
    rf"^countif\s*\(\s*['\"]Y['\"]\s*,\s*{_MACRO_TARGET}\s*\)"
    r"\s*(==|!=|>=|<=|>|<)\s*([0-9]+)$",
    re.IGNORECASE,
)
_COUNTIFOP = re.compile(
    rf"^countifop\s*\(\s*['\"]==['\"]\s*,\s*['\"]Y['\"]\s*,\s*{_MACRO_TARGET}\s*\)"
    r"\s*(==|!=|>=|<=|>|<)\s*([0-9]+)$",
    re.IGNORECASE,
)


def parse_limesurvey_condition(
    expression: str,
    references: Mapping[str, ConditionReference],
    current_field_code: Optional[str] = None,
) -> Dict[str, Any] | None:
    """Return a neutral condition tree, or ``None`` for an unconditional expression."""
    normalized = _strip_outer_parentheses((expression or "").strip())
    if not normalized or normalized == "1":
        return None
    if normalized == "0":
        return {
            "type": "constant",
            "value": False,
        }

    parts = _split_logical(normalized, "or")
    if len(parts) > 1:
        return {
            "type": "any",
            "conditions": [_required(parse_limesurvey_condition(part, references, current_field_code), part) for part in parts],
        }

    parts = _split_logical(normalized, "and")
    if len(parts) > 1:
        return {
            "type": "all",
            "conditions": [_required(parse_limesurvey_condition(part, references, current_field_code), part) for part in parts],
        }

    if re.match(r"^not\b", normalized, re.IGNORECASE):
        nested = re.sub(r"^not\b", "", normalized, count=1, flags=re.IGNORECASE).strip()
        return {
            "type": "not",
            "condition": _required(parse_limesurvey_condition(nested, references, current_field_code), nested),
        }
    if normalized.startswith("!"):
        nested = normalized[1:].strip()
        return {
            "type": "not",
            "condition": _required(parse_limesurvey_condition(nested, references, current_field_code), nested),
        }

    selection_count = next((pattern.match(normalized) for pattern in (_COUNT, _COUNTIF, _COUNTIFOP) if pattern.match(normalized)), None)
    if selection_count:
        selector, operator, value = selection_count.groups()
        parts = selector.split('.')
        macro = parts.pop(0)
        referenced_field = parts.pop(0) if macro.lower() == 'that' and parts else None
        if any(part.lower() not in {'naok', 'code', 'nocomments'} for part in parts):
            raise UnsupportedConditionError(f'Unsupported LimeSurvey count selector: {selector}')
        target = _resolve_macro_reference(macro, referenced_field, references, current_field_code)
        count_type = _count_type(normalized, target[0], parts, references)
        return {
            "type": count_type,
            "responseReference": _reference_payload(target),
            "operator": _OPERATORS[operator],
            "value": int(value),
        }

    empty_match = re.match(r"^(?:is_empty|empty)\s*\(([^)]+)\)$", normalized, re.IGNORECASE)
    if empty_match:
        return {
            "type": "not-answered",
            "responseReference": _reference_payload(_resolve_reference(empty_match.group(1), references)),
        }

    comparison = _COMPARISON.match(normalized)
    if comparison:
        reference, operator, raw_value = comparison.groups()
        if reference.lower() == 'this':
            reference = _current_scalar_reference(current_field_code, references)
        return {
            "type": "comparison",
            "responseReference": _reference_payload(_resolve_reference(reference, references)),
            "operator": _OPERATORS[operator],
            "value": _literal(raw_value),
        }

    bare_reference = re.match(r"^([A-Za-z0-9_]+(?:X[0-9]+X[0-9]+X[0-9]+)?(?:_[A-Za-z0-9]+)*)(?:\.(?:NAOK|code))?$", normalized)
    if bare_reference:
        return {
            "type": "answered",
            "responseReference": _reference_payload(_resolve_reference(bare_reference.group(1), references)),
        }

    raise UnsupportedConditionError(f"Unsupported LimeSurvey condition: {expression}")


def _count_type(expression, code, selectors, references) -> str:
    """Distinguish selected options from answered cells before building the tree."""
    if not isinstance(references, ConditionReferenceIndex):
        return 'selection-count'
    question = references.questions.get(code, {})
    native = question.get('type')
    selected_only = not expression.lower().startswith('count(') and not re.match(r'^count\s*\(', expression, re.I)
    other = str(question.get('other', '')).upper() == 'Y'
    excludes_comments = 'nocomments' in [part.lower() for part in selectors]
    if native in {'M', 'P'} and not other and (native == 'M' or selected_only or excludes_comments):
        return 'selection-count'
    if native == 'R' and not selected_only:
        return 'selection-count'
    if native in {'Q', ';', ':', 'F', 'H', 'B', '1'} and not selected_only:
        attributes = (question.get('result') or {}).get('attributes') or question.get('attributes') or {}
        if native != ':' or str(attributes.get('multiflexible_checkbox', '')).upper() not in {'1', 'Y'}:
            return 'answered-count'
    raise UnsupportedConditionError(
        f'Count expression for "{code}" (LimeSurvey type {native}) includes responses or filters '
        'that cannot be counted faithfully by the supported neutral condition. The condition was omitted.'
    )


def _current_scalar_reference(current, references):
    if not current:
        raise UnsupportedConditionError('The "this" variable requires a current scalar question context.')
    if isinstance(references, ConditionReferenceIndex):
        native = references.questions.get(current, {}).get('type')
        if native not in {'S', 'T', 'N', 'D', 'Y', 'G', 'L', '!'}:
            raise UnsupportedConditionError('The "this" variable requires a specific response cell; question-level context is insufficient.')
    return current



def _resolve_macro_reference(
    macro: str,
    referenced_field: Optional[str],
    references: Mapping[str, ConditionReference],
    current_field_code: Optional[str],
) -> ConditionReference:
    if macro.lower() == "that":
        if not referenced_field:
            raise UnsupportedConditionError('The "that" macro requires a question code.')
        return _resolve_reference(referenced_field, references)
    if not current_field_code:
        raise UnsupportedConditionError(
            'The "self" macro requires the current question context, which is not available here.'
        )
    if referenced_field and referenced_field.lower() not in {"naok", "code"}:
        raise UnsupportedConditionError(
            f'Unsupported LimeSurvey self sub-selector: {referenced_field}'
        )
    return _resolve_reference(current_field_code, references)


def _reference_payload(reference: ConditionReference) -> Dict[str, str]:
    field_code, response_item_code = reference
    payload = {"fieldCode": field_code}
    if response_item_code:
        payload["responseItemCode"] = response_item_code
    return payload



def _literal(raw_value: str) -> Any:
    value = _strip_outer_parentheses(raw_value.strip())
    if re.fullmatch(r'"(?:[^"\\]|\\.)*"', value):
        try:
            return json.loads(value)
        except ValueError as error:
            raise UnsupportedConditionError(f"Unsupported quoted condition value: {raw_value}") from error
    if re.fullmatch(r"'(?:[^'\\]|\\.)*'", value):
        return value[1:-1].replace("\\'", "'").replace("\\\\", "\\")
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite numeric literal")
        return int(number) if number.is_integer() else number
    except ValueError as error:
        raise UnsupportedConditionError(f"Unsupported condition literal: {raw_value}") from error


def _required(condition: Dict[str, Any] | None, expression: str) -> Dict[str, Any]:
    if condition is None:
        return {"type": "constant", "value": True}
    return condition


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
