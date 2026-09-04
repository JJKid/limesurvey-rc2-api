"""
FastAPI bootstrap module.

This file is intentionally small and declarative:
1) Build the app object
2) Register global middleware
3) Register lifecycle hooks (startup/shutdown)
4) Mount routers by feature domain

All business logic lives in `routers/` and `services/`.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import APP_NAME, CORS_ORIGINS
from routers.auth import router as auth_router
from routers.health import router as health_router
from routers.responses import router as responses_router
from routers.surveys import router as surveys_router
from routers.survey_structures import router as survey_structures_router
from infrastructure.redis_client import close_redis, initialize_redis


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Open shared clients once and close them when the process stops."""
    await initialize_redis()
    try:
        yield
    finally:
        await close_redis()


app = FastAPI(
    title=APP_NAME,
    version="2.0.0",
    description=(
        "Adapter that authenticates against LimeSurvey RemoteControl 2, "
        "loads survey definitions and responses, and normalizes surveys to "
        "the shared SurveyStructure contract."
    ),
    lifespan=lifespan,
    openapi_tags=[
        {"name": "health", "description": "Service readiness and dependency status."},
        {"name": "limesurvey-sessions", "description": "Open and close temporary LimeSurvey sessions."},
        {"name": "surveys", "description": "List surveys visible to the connected LimeSurvey account."},
        {"name": "survey-structures", "description": "Normalize remote surveys or uploaded .lss files."},
        {"name": "limesurvey-responses", "description": "Read-only response exports from LimeSurvey."},
    ],
)


# Global middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-LimeSurvey-Session"],
)

# Router registration (keeps public paths unchanged)
app.include_router(health_router)
app.include_router(auth_router)
app.include_router(surveys_router)
app.include_router(survey_structures_router)
app.include_router(responses_router)
