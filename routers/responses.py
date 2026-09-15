"""Read-only LimeSurvey response export endpoints."""

import asyncio
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response

from core.security import AuthenticatedIdentity, verify_token
from schemas import SurveyResponseDataset
from services.error_mapper import raise_limesurvey_error
from services.remote_response_loader import (
    InvalidResponseExportError,
    ResponseExportTooLargeError,
    load_responses,
)
from services.response_export_rate_limiter import enforce_response_export_rate_limit
from services.limesurvey_session_service import resume_limesurvey_client


router = APIRouter(tags=["limesurvey-responses"])


@router.get("/survey_responses/{sid}")
async def get_survey_responses(
    sid: int,
    accept: str = Header("application/json", alias="Accept"),
    session_key: str = Header(..., alias="X-LimeSurvey-Session"),
    language: Optional[str] = Query(None),
    completion_status: Literal["all", "complete", "incomplete"] = Query("all", alias="completionStatus"),
    heading_type: Literal["code", "full", "abbreviated"] = Query("code", alias="headingType"),
    response_type: Literal["short", "long"] = Query("short", alias="responseType"),
    from_response_id: Optional[int] = Query(None, ge=1, alias="fromResponseId"),
    to_response_id: Optional[int] = Query(None, ge=1, alias="toResponseId"),
    fields: Optional[List[str]] = Query(None),
    auth: AuthenticatedIdentity = Depends(verify_token),
):
    """Export responses visible to the active LimeSurvey user as JSON or CSV.

    The endpoint is read-only. It never caches response rows and never writes
    response contents to logs. Use ``Accept: text/csv`` for the original CSV
    export or ``Accept: application/json`` for a ``SurveyResponseDataset``.
    """
    if from_response_id and to_response_id and from_response_id > to_response_id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_RESPONSE_RANGE",
                "message": "fromResponseId must be less than or equal to toResponseId.",
            },
        )
    normalized_fields = _normalize_fields(fields)
    api = await resume_limesurvey_client(session_key, auth)
    await enforce_response_export_rate_limit(session_key, sid)
    file_format = "csv" if "text/csv" in accept.lower() else "json"
    try:
        export = await load_responses(
            api=api,
            sid=sid,
            file_format=file_format,
            language=language,
            completion_status=completion_status,
            heading_type=heading_type,
            response_type=response_type,
            from_response_id=from_response_id,
            to_response_id=to_response_id,
            fields=normalized_fields,
        )
        if file_format == "csv":
            return Response(
                content=export.content,
                media_type="text/csv",
                headers={
                    "Content-Disposition": f'attachment; filename="survey-{sid}-responses.csv"',
                    "Cache-Control": "no-store",
                },
            )
        return Response(
            content=_json_response(sid, language, export.responses or []),
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )
    except (TimeoutError, asyncio.TimeoutError) as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "LS_RESPONSE_EXPORT_TIMEOUT",
                "message": "LimeSurvey did not finish exporting responses within the configured timeout.",
            },
        ) from exc
    except ResponseExportTooLargeError as exc:
        raise HTTPException(
            status_code=413,
            detail={"code": "LS_RESPONSE_EXPORT_TOO_LARGE", "message": str(exc)},
        ) from exc
    except InvalidResponseExportError as exc:
        raise HTTPException(
            status_code=502,
            detail={"code": "INVALID_LS_RESPONSE_EXPORT", "message": str(exc)},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        await raise_limesurvey_error(session_key, exc, f"exporting responses for sid {sid}")


def _normalize_fields(fields: Optional[List[str]]) -> Optional[List[str]]:
    from core.config import LS_RESPONSES_MAX_FIELDS

    if not fields:
        return None
    normalized = []
    for item in fields:
        normalized.extend(part.strip() for part in item.split(",") if part.strip())
    if len(normalized) > LS_RESPONSES_MAX_FIELDS:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "TOO_MANY_RESPONSE_FIELDS",
                "message": f"At most {LS_RESPONSES_MAX_FIELDS} response fields may be requested.",
            },
        )
    return list(dict.fromkeys(normalized))


def _json_response(sid: int, language: Optional[str], responses: List[dict]) -> bytes:
    import json

    dataset = SurveyResponseDataset(
        surveyId=str(sid),
        language=language,
        responses=responses,
    )
    return json.dumps(
        dataset.model_dump(exclude_none=True),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
