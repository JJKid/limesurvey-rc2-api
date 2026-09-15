"""Scan grouping and quoted literals; never evaluate source expressions."""

import re
from .condition_references import UnsupportedConditionError


def top_level_positions(expression: str) -> set[int]:
    positions = set()
    depth = 0
    quote = ""
    escaped = False
    for index, character in enumerate(expression):
        if quote:
            if character == quote and not escaped:
                quote = ""
            escaped = character == "\\" and not escaped
            continue
        if depth == 0:
            positions.add(index)
        if character in {"'", '"'}:
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth < 0:
                raise UnsupportedConditionError("Condition contains an unmatched closing parenthesis.")
    if depth or quote:
        raise UnsupportedConditionError("Condition contains an unclosed parenthesis or quoted value.")
    return positions


def split_logical(expression: str, operator: str) -> list[str]:
    positions = top_level_positions(expression)
    symbolic = r"\|\|" if operator == "or" else "&&"
    parts = []
    start = 0
    for match in re.finditer(rf"\b{operator}\b|{symbolic}", expression, re.IGNORECASE):
        if match.start() not in positions:
            continue
        parts.append(expression[start:match.start()].strip())
        start = match.end()
    parts.append(expression[start:].strip())
    if any(not part for part in parts):
        raise UnsupportedConditionError("Condition is missing an operand beside a logical operator.")
    return parts


def strip_outer_parentheses(expression: str) -> str:
    result = expression.strip()
    while result.startswith("(") and result.endswith(")"):
        if top_level_positions(result) != {0}:
            break
        result = result[1:-1].strip()
    return result
