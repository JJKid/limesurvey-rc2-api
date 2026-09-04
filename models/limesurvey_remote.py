"""Typed shapes returned by the Citric operations used by this adapter."""

from typing import Any, Dict, List, TypedDict


class LimeSurveySurveyRow(TypedDict, total=False):
    sid: int
    surveyls_title: str
    active: str
    language: str


class LimeSurveyGroupRow(TypedDict, total=False):
    gid: int
    sid: int
    group_name: str
    group_order: int
    grelevance: str
    language: str


class LimeSurveyQuestionRow(TypedDict, total=False):
    qid: int
    sid: int
    gid: int
    parent_qid: int
    title: str
    question: str
    type: str
    mandatory: str
    relevance: str
    question_order: int
    language: str
    result: Dict[str, Any]
    grelevance: str
    full_condition: str


LimeSurveySurveyRows = List[LimeSurveySurveyRow]
LimeSurveyGroupRows = List[LimeSurveyGroupRow]
LimeSurveyQuestionRows = List[LimeSurveyQuestionRow]
LimeSurveyPropertyMap = Dict[str, Any]
