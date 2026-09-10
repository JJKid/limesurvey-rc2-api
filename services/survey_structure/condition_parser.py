"""Translate the supported LimeSurvey condition subset into portable condition trees."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Tuple


ConditionReference = Tuple[str, Optional[str]]


class UnsupportedConditionError(ValueError):
    """The source expression cannot be represented by the portable condition contract."""


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

_MACRO_TARGET = r"(that|self)(?:\.([A-Za-z0-9_]+))?(?:\.(?:NAOK|code))?"
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
        macro, referenced_field, operator, value = selection_count.groups()
        return {
            "type": "selection-count",
            "reference": _reference_payload(
                _resolve_macro_reference(macro, referenced_field, references, current_field_code)
            ),
            "operator": _OPERATORS[operator],
            "value": int(value),
        }

    empty_match = re.match(r"^(?:is_empty|empty)\s*\(([^)]+)\)$", normalized, re.IGNORECASE)
    if empty_match:
        return {
            "type": "not-answered",
            "reference": _reference_payload(_resolve_reference(empty_match.group(1), references)),
        }

    comparison = _COMPARISON.match(normalized)
    if comparison:
        reference, operator, raw_value = comparison.groups()
        return {
            "type": "comparison",
            "reference": _reference_payload(_resolve_reference(reference, references)),
            "operator": _OPERATORS[operator],
            "value": _literal(raw_value),
        }

    bare_reference = re.match(r"^([A-Za-z0-9_]+(?:X[0-9]+X[0-9]+X[0-9]+)?(?:_[A-Za-z0-9]+)*)(?:\.(?:NAOK|code))?$", normalized)
    if bare_reference:
        return {
            "type": "answered",
            "reference": _reference_payload(_resolve_reference(bare_reference.group(1), references)),
        }

    raise UnsupportedConditionError(f"Unsupported LimeSurvey condition: {expression}")


def build_condition_references(
    questions: List[Dict[str, Any]],
    survey_id: str,
) -> Dict[str, ConditionReference]:
    """Index native ids, LSS aliases, SGQA names and canonical field references."""
    result: Dict[str, ConditionReference] = {}
    parents: Dict[str, Dict[str, Any]] = {}
    for question in questions:
        qid = _text(question.get("qid"))
        parent_qid = _text(question.get("parent_qid") or "0")
        if qid and parent_qid in {"", "0"}:
            parents[qid] = question

    for qid, question in parents.items():
        field_code = _text(question.get("title")) or qid
        gid = _text(question.get("gid"))
        # LimeSurvey condition expressions are not consistent about identifiers.
        # Depending on their origin, the same question can appear as its public
        # code (G01Q02), numeric qid (244), LSS alias (Q244), or SGQA token.
        base_tokens = {field_code, qid, f"Q{qid}"}
        if survey_id and gid and qid:
            base_tokens.add(f"{survey_id}X{gid}X{qid}")
        for token in base_tokens:
            if token:
                result[token] = (field_code, None)

        for child in questions:
            if _text(child.get("parent_qid")) != qid:
                continue
            item_code = _text(child.get("title")) or _text(child.get("qid"))
            child_qid = _text(child.get("qid"))
            if not item_code:
                continue
            for base in base_tokens:
                if not base:
                    continue
                result[f"{base}_{item_code}"] = (field_code, item_code)
                result[f"{base}{item_code}"] = (field_code, item_code)
            # An exported .lss condition can use Q<parent qid>_S<child qid>
            # instead of the public question and subquestion codes.
            if qid and child_qid:
                result[f"Q{qid}_S{child_qid}"] = (field_code, item_code)
    return result


def _resolve_reference(
    raw_reference: str,
    references: Mapping[str, ConditionReference],
) -> ConditionReference:
    token = re.sub(r"\.NAOK$", "", (raw_reference or "").strip(), flags=re.IGNORECASE)
    if token in references:
        return references[token]
    raise UnsupportedConditionError(
        f'LimeSurvey condition reference "{token}" could not be matched to any '
        "imported question or subquestion. The condition was omitted."
    )


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


def _split_logical(expression: str, operator: str) -> List[str]:
    parts: List[str] = []
    start = 0
    depth = 0
    quote = ""
    symbolic_operator = r"\|\|" if operator == "or" else "&&"
    pattern = re.compile(rf"\b{operator}\b|{symbolic_operator}", re.IGNORECASE)
    for match in pattern.finditer(expression):
        segment = expression[start:match.start()]
        depth, quote = _scan_state(segment, depth, quote)
        if depth == 0 and not quote:
            parts.append(expression[start:match.start()].strip())
            start = match.end()
    if not parts:
        return [expression]
    parts.append(expression[start:].strip())
    return [part for part in parts if part]


def _scan_state(text: str, depth: int, quote: str) -> Tuple[int, str]:
    escaped = False
    for character in text:
        if quote:
            if character == quote and not escaped:
                quote = ""
            escaped = character == "\\" and not escaped
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
        escaped = False
    return depth, quote


def _strip_outer_parentheses(expression: str) -> str:
    result = expression.strip()
    while result.startswith("(") and result.endswith(")") and _outer_pair_wraps_all(result):
        result = result[1:-1].strip()
    return result


def _outer_pair_wraps_all(expression: str) -> bool:
    depth = 0
    quote = ""
    escaped = False
    for index, character in enumerate(expression):
        if quote:
            if character == quote and not escaped:
                quote = ""
            escaped = character == "\\" and not escaped
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0 and index != len(expression) - 1:
                return False
        escaped = False
    return depth == 0


def _literal(raw_value: str) -> Any:
    value = _strip_outer_parentheses(raw_value.strip())
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in {"null", "none"}:
        return None
    try:
        number = float(value)
        return int(number) if number.is_integer() else number
    except ValueError as error:
        raise UnsupportedConditionError(f"Unsupported condition literal: {raw_value}") from error


def _required(condition: Dict[str, Any] | None, expression: str) -> Dict[str, Any]:
    if condition is None:
        raise UnsupportedConditionError(f"Unconditional expression inside condition tree: {expression}")
    return condition


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
