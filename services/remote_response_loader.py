"""Load LimeSurvey response datasets with bounded resource usage."""

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence
from pydantic import ValidationError
from schemas import SurveyResponseDataset

from core.config import LS_RESPONSES_MAX_BYTES, LS_RESPONSES_TIMEOUT_SECONDS
from services.remote_call_executor import run_remote_call


class ResponseExportTooLargeError(ValueError):
    """Raised when LimeSurvey returns more response data than configured."""


class InvalidResponseExportError(ValueError):
    """Raised when LimeSurvey returns JSON with an unexpected structure."""


@dataclass(frozen=True)
class RemoteResponseExport:
    """Validated response-export bytes and optional decoded response records."""

    content: bytes
    responses: Optional[List[Dict[str, Any]]] = None


async def load_responses(
    *,
    api: Any,
    sid: int,
    file_format: str,
    language: Optional[str],
    completion_status: str,
    heading_type: str,
    response_type: str,
    from_response_id: Optional[int],
    to_response_id: Optional[int],
    fields: Optional[Sequence[str]],
) -> RemoteResponseExport:
    """Export responses once, enforce timeout/size limits, and decode JSON safely."""
    content = await asyncio.wait_for(
        run_remote_call(
            api,
            api.survey.export_responses,
            sid,
            file_format=file_format,
            language=language,
            completion_status=completion_status,
            heading_type=heading_type,
            response_type=response_type,
            from_response_id=from_response_id,
            to_response_id=to_response_id,
            fields=fields,
        ),
        timeout=LS_RESPONSES_TIMEOUT_SECONDS,
    )
    if not isinstance(content, bytes):
        raise InvalidResponseExportError("LimeSurvey response export did not return bytes.")
    if len(content) > LS_RESPONSES_MAX_BYTES:
        raise ResponseExportTooLargeError(
            f"LimeSurvey response export exceeds the configured {LS_RESPONSES_MAX_BYTES}-byte limit."
        )
    if file_format == "csv":
        return RemoteResponseExport(content=content)

    try:
        decoded = json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidResponseExportError("LimeSurvey returned an invalid JSON response export.") from exc
    responses = decoded.get("responses") if isinstance(decoded, dict) else None
    if not isinstance(responses, list) or not all(isinstance(item, dict) for item in responses):
        raise InvalidResponseExportError(
            'LimeSurvey JSON export must contain a "responses" array of objects.'
        )
    try:
        SurveyResponseDataset(surveyId=str(sid), responses=responses)
    except ValidationError as exc:
        raise InvalidResponseExportError("LimeSurvey returned values that are not valid JSON response data.") from exc
    return RemoteResponseExport(content=content, responses=responses)
