"""SurveyStructure endpoints for live LimeSurvey data and uploaded .lss files."""

import asyncio
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile

from core.config import LS_SURVEY_LOAD_TIMEOUT_SECONDS
from core.security import AuthenticatedIdentity, verify_token
from services.error_mapper import raise_limesurvey_error
from services.limesurvey_session_service import resume_limesurvey_client
from services.remote_survey_loader import SurveyGroupsNotFoundError
from services.remote_survey_structure_loader import load_remote_survey_structure
from services.survey_structure import (
    SurveyStructureContractError,
    SurveyStructureSourceError,
    survey_structure_from_lss,
)


router = APIRouter(tags=["survey-structures"])
logger = logging.getLogger("uvicorn.error")


@router.get(
    "/survey_structure/{sid}",
    response_model=Dict[str, Any],
    summary="Normalize a live LimeSurvey survey",
)
async def get_survey_structure(
    sid: int,
    session_key: str = Header(..., alias="X-LimeSurvey-Session"),
    language: Optional[str] = Query(
        None,
        description="Language code to request; the survey base language is used when omitted.",
    ),
    refresh: bool = Query(
        False,
        description="Bypass the normalized-question cache and read the live survey again.",
    ),
    auth: AuthenticatedIdentity = Depends(verify_token),
) -> Dict[str, Any]:
    """Return a validated SurveyLoadResult for one accessible survey id."""
    api = resume_limesurvey_client(session_key, auth)
    try:
        return await load_remote_survey_structure(api, sid, language, refresh=refresh)
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "LS_SURVEY_LOAD_TIMEOUT",
                "message": (
                    "LimeSurvey did not provide the complete survey structure "
                    f"within {int(LS_SURVEY_LOAD_TIMEOUT_SECONDS)} seconds."
                ),
            },
        ) from exc
    except SurveyStructureContractError as exc:
        logger.exception("Remote normalization produced an invalid SurveyStructure for sid=%s", sid)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except SurveyGroupsNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise_limesurvey_error(session_key, exc, f"normalizing survey structure for sid {sid}")


@router.post(
    "/survey_structures/from-lss",
    response_model=Dict[str, Any],
    summary="Normalize an uploaded LimeSurvey .lss file",
)
async def import_lss_as_survey_structure(
    file: UploadFile = File(..., description="LimeSurvey .lss XML survey structure file"),
    language: Optional[str] = Query(None, description="Language available inside the uploaded file."),
    _auth: AuthenticatedIdentity = Depends(verify_token),
) -> Dict[str, Any]:
    """Read an .lss file without opening a remote LimeSurvey session."""
    filename = (file.filename or "").lower()
    if not filename.endswith(".lss"):
        raise HTTPException(status_code=400, detail="Expected a file with .lss extension")
    content = await file.read(20 * 1024 * 1024 + 1)
    try:
        return survey_structure_from_lss(content, language)
    except SurveyStructureSourceError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SurveyStructureContractError as exc:
        logger.exception("LSS normalization produced an invalid SurveyStructure file=%s", file.filename)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
