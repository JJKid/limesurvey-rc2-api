"""Normalize survey navigation settings and group-level content and conditions."""

from typing import Any, Dict, List, Optional
from .condition_parser import UnsupportedConditionError, parse_limesurvey_condition
from .source_values import _clean_html, _text, _number, _optional_number, _compact, _yes, _issue
from .visibility_normalizer import log_unsupported_condition

def normalize_group(
    group: Dict[str, Any],
    condition_references: Dict[str, tuple[str, Optional[str]]],
    issues: List[Dict[str, Any]],
) -> Dict[str, Any]:
    result = {
        "id": _text(group.get("gid")),
        "order": _number(group.get("group_order"), 0),
    }
    title = _clean_html(group.get("group_name"))
    description = _clean_html(group.get("description"))
    if title:
        result["title"] = title
    if description:
        result["description"] = description
    relevance = _text(group.get("grelevance")).strip()
    group_id = _text(group.get("gid")).strip()
    if group_id or relevance:
        result["source"] = _compact({
            "platform": "limesurvey",
            "groupId": group_id or None,
            "extensions": ([{
                "type": "limesurvey-group",
                "version": "1.0.0",
                "groupRelevanceExpression": relevance,
            }] if relevance else None),
        })
    if relevance and relevance != "1":
        try:
            condition = parse_limesurvey_condition(relevance, condition_references)
            if condition:
                result["visibility"] = {"condition": condition}
        except UnsupportedConditionError as error:
            log_unsupported_condition(relevance, scope="group", owner=group_id)
            issues.append(_issue(
                "warning", "INVALID_EXPRESSION", str(error),
                details={"sourceExpression": relevance, "scope": "group"},
            ))
    return result


def normalize_settings(survey: Dict[str, Any], language: Dict[str, Any]) -> Dict[str, Any]:
    layout = {"A": "all", "G": "group", "S": "question"}.get(_text(survey.get("format")).upper())
    show_group = _text(survey.get("showgroupinfo")).upper()
    return _compact({
        "layout": layout,
        "showWelcome": _yes(survey.get("showwelcome")) if survey.get("showwelcome") is not None else None,
        "showProgress": _yes(survey.get("showprogress")) if survey.get("showprogress") is not None else None,
        "allowPrevious": _yes(survey.get("allowprev")) if survey.get("allowprev") is not None else None,
        "showGroupName": show_group in {"B", "N"} if show_group else None,
        "showGroupDescription": show_group in {"B", "D"} if show_group else None,
        "questionIndex": {
            -1: "inherit",
            0: "disabled",
            1: "incremental",
            2: "full",
        }.get(int(_optional_number(survey.get("questionindex")) or 0)),
        # LimeSurvey can export -1 as an inherited/default sentinel. The
        # portable setting stores the effective non-negative delay instead.
        "navigationDelay": max(0, _optional_number(survey.get("navigationdelay")) or 0),
        "welcomeText": _clean_html(language.get("surveyls_welcometext")) or None,
        "endText": _clean_html(language.get("surveyls_endtext")) or None,
        "policyNotice": _clean_html(language.get("surveyls_policy_notice")) or None,
    })
