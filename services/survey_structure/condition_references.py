"""Resolve imported identifiers without choosing between ambiguous aliases."""

from collections import defaultdict
from typing import Any, Mapping, Optional
import re

ConditionReference = tuple[str, Optional[str]]


class UnsupportedConditionError(ValueError):
    """The source expression cannot be represented faithfully by the contract."""


class ConditionReferenceIndex(dict[str, ConditionReference]):
    """Temporary import index; ambiguous names are never usable references."""

    def __init__(self) -> None:
        super().__init__()
        self.ambiguous_aliases: set[str] = set()
        self.questions: dict[str, dict[str, Any]] = {}

    def add(self, alias: str, target: ConditionReference) -> None:
        if not alias or alias in self.ambiguous_aliases:
            return
        if alias in self and self[alias] != target:
            del self[alias]
            self.ambiguous_aliases.add(alias)
        else:
            self[alias] = target


def build_condition_references(questions: list[dict[str, Any]], survey_id: str) -> ConditionReferenceIndex:
    """Index codes, qid, Q<qid>, SGQA and actual parent/child relationships once."""
    result = ConditionReferenceIndex()
    parents = []
    children = defaultdict(list)
    for question in questions:
        parent_id = str(question.get("parent_qid") or "0").strip()
        if parent_id in {"", "0"}:
            parents.append(question)
        else:
            children[parent_id].append(question)
    for question in parents:
        qid = str(question.get("qid") or "").strip()
        code = str(question.get("title") or "").strip()
        gid = str(question.get("gid") or "").strip()
        if not code:
            continue
        result.questions[code] = question
        tokens = {code}
        if qid:
            tokens.update((qid, f"Q{qid}"))
        if survey_id and gid and qid:
            tokens.add(f"{survey_id}X{gid}X{qid}")
        for token in tokens:
            result.add(token, (code, None))
        for child in children[qid]:
            item_code = str(child.get("title") or "").strip()
            child_qid = str(child.get("qid") or "").strip()
            if not item_code:
                continue
            for token in tokens:
                result.add(f"{token}_{item_code}", (code, item_code))
                result.add(f"{token}{item_code}", (code, item_code))
            if child_qid:
                result.add(f"Q{qid}_S{child_qid}", (code, item_code))
    return result


def resolve_reference(raw: str, references: Mapping[str, ConditionReference]) -> ConditionReference:
    token = re.sub(r"\.(NAOK|code)$", "", raw.strip(), flags=re.IGNORECASE)
    if isinstance(references, ConditionReferenceIndex) and token in references.ambiguous_aliases:
        raise UnsupportedConditionError(
            f'LimeSurvey condition alias "{token}" identifies more than one imported response. '
            "The condition was omitted; use an unambiguous question code in LimeSurvey."
        )
    if token in references:
        return references[token]
    raise UnsupportedConditionError(
        f'LimeSurvey condition reference "{token}" could not be matched to any '
        "imported question or subquestion. The condition was omitted."
    )
