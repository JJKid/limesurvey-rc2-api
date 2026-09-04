"""Parse LimeSurvey survey-structure XML files before canonical adaptation."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional

from services.survey_structure.normalizer import (
    SurveyStructureSourceError,
    build_survey_structure,
)


SUPPORTED_LSS_DB_VERSIONS = {"348", "623", "643", "708"}
MAX_LSS_BYTES = 20 * 1024 * 1024


def survey_structure_from_lss(content: bytes, language: Optional[str] = None) -> Dict[str, Any]:
    """Convert one validated LimeSurvey ``.lss`` XML file to SurveyLoadResult.

    This path reads the uploaded file only. It does not open a RemoteControl 2
    session or issue HTTP requests to LimeSurvey.
    """
    root = _parse_document(content)
    db_version = _element_text(root.find("DBVersion"))
    if db_version not in SUPPORTED_LSS_DB_VERSIONS:
        raise SurveyStructureSourceError(
            f"Unsupported LSS DBVersion {db_version or '(missing)'}. "
            f"Accepted versions: {', '.join(sorted(SUPPORTED_LSS_DB_VERSIONS))}."
        )

    languages = [_element_text(item) for item in root.findall("./languages/language") if _element_text(item)]
    surveys = _rows(root, "surveys")
    if not surveys:
        raise SurveyStructureSourceError("LSS file does not contain a surveys row.")
    survey = surveys[0]
    selected_language = language or _text(survey.get("language")).strip() or (languages[0] if languages else "")
    if language and languages and language not in languages:
        raise SurveyStructureSourceError(
            f"Language {language} is not available in this LSS file ({', '.join(languages)})."
        )

    question_l10ns = _index_language_rows(_rows(root, "question_l10ns"), "qid", selected_language)
    group_l10ns = _index_language_rows(_rows(root, "group_l10ns"), "gid", selected_language)
    answer_l10ns = _index_language_rows(_rows(root, "answer_l10ns"), "aid", selected_language)
    survey_language = _select_language_row(
        _rows(root, "surveys_languagesettings"), "surveyls_language", selected_language
    )

    groups = [
        {**row, **group_l10ns.get(_text(row.get("gid")), {})}
        for row in _rows(root, "groups")
    ]
    answers_by_qid = _group_answers(root, answer_l10ns, selected_language)
    attributes_by_qid = _group_attributes(root, selected_language)
    conditions_by_qid = _group_conditions(root)
    questions = _merge_questions(
        root,
        question_l10ns,
        answers_by_qid,
        attributes_by_qid,
        conditions_by_qid,
        selected_language,
    )

    return build_survey_structure({
        "survey": survey,
        "language": survey_language,
        "groups": groups,
        "questions": questions,
        "source": {
            "surveyId": survey.get("sid"),
            "databaseSchemaVersion": db_version,
            "selectedLanguage": selected_language,
            "availableLanguages": languages,
        },
    }, source_format="lss")


def _parse_document(content: bytes) -> ET.Element:
    """Reject unsafe or unsupported XML and return the document root."""
    if len(content) > MAX_LSS_BYTES:
        raise SurveyStructureSourceError("LSS file exceeds the 20 MiB limit.")
    prefix = content[:4096].decode("utf-8", errors="ignore").upper()
    if "<!DOCTYPE" in prefix or "<!ENTITY" in prefix:
        raise SurveyStructureSourceError("LSS files with DTD or entity declarations are not accepted.")
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise SurveyStructureSourceError(f"Invalid LSS XML: {exc}.") from exc
    if root.tag != "document" or _element_text(root.find("LimeSurveyDocType")) != "Survey":
        raise SurveyStructureSourceError("The uploaded XML is not a LimeSurvey survey structure file.")
    return root


def _group_answers(
    root: ET.Element,
    localizations: Dict[str, Dict[str, Any]],
    language: str,
) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in _rows(root, "answers"):
        merged = {**row, **localizations.get(_text(row.get("aid")), {})}
        if language and merged.get("language") and merged.get("language") != language:
            continue
        grouped[_text(row.get("qid"))].append(merged)
    return grouped


def _group_attributes(root: ET.Element, language: str) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = defaultdict(dict)
    for row in _rows(root, "question_attributes"):
        row_language = _text(row.get("language")).strip()
        if row_language and language and row_language != language:
            continue
        grouped[_text(row.get("qid"))][_text(row.get("attribute"))] = row.get("value")
    return grouped


def _group_conditions(root: ET.Element) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in _rows(root, "conditions"):
        grouped[_text(row.get("qid"))].append(row)
    return grouped


def _merge_questions(
    root: ET.Element,
    localizations: Dict[str, Dict[str, Any]],
    answers_by_qid: Dict[str, List[Dict[str, Any]]],
    attributes_by_qid: Dict[str, Dict[str, Any]],
    conditions_by_qid: Dict[str, List[Dict[str, Any]]],
    language: str,
) -> List[Dict[str, Any]]:
    questions: List[Dict[str, Any]] = []
    for row in [*_rows(root, "questions"), *_rows(root, "subquestions")]:
        qid = _text(row.get("qid"))
        merged = {**row, **localizations.get(qid, {})}
        if language and merged.get("language") and merged.get("language") != language:
            continue
        merged["result"] = {
            "question": merged.get("question"),
            "help": merged.get("help"),
            "answeroptions": {
                _text(answer.get("code")): {
                    "answer": answer.get("answer") or answer.get("code"),
                    "sortorder": answer.get("sortorder"),
                }
                for answer in answers_by_qid.get(qid, [])
            },
            "attributes": attributes_by_qid.get(qid),
        }
        if conditions_by_qid.get(qid):
            merged["conditions"] = conditions_by_qid[qid]
        questions.append(merged)
    return questions


def _rows(root: ET.Element, section_name: str) -> List[Dict[str, str]]:
    return [
        {child.tag: _element_text(child) for child in row}
        for row in root.findall(f"./{section_name}/rows/row")
    ]


def _index_language_rows(
    rows: Iterable[Dict[str, Any]],
    key: str,
    language: str,
) -> Dict[str, Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_text(row.get(key))].append(row)
    return {
        identifier: _select_language_row(values, "language", language)
        for identifier, values in grouped.items()
    }


def _select_language_row(
    rows: Iterable[Dict[str, Any]],
    language_key: str,
    language: str,
) -> Dict[str, Any]:
    values = list(rows)
    return next(
        (row for row in values if _text(row.get(language_key)) == language),
        values[0] if values else {},
    )


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _element_text(element: Optional[ET.Element]) -> str:
    return "" if element is None else (element.text or "")
