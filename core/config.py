"""
Application configuration loaded from environment variables.

The goal of this module is to keep app.py minimal: app bootstrap should only
wire components, while configuration lives here in one place.
"""

from pathlib import Path
import os

from dotenv import load_dotenv


def _load_env_files() -> None:
    """
    Load .env values from:
      1) local service folder (.env next to app.py)
      2) repo root .env (if available)
    """
    local_env = Path(__file__).resolve().parents[1] / ".env"
    load_dotenv(local_env, override=False)

    resolved_path = Path(__file__).resolve()
    root_env = None
    if len(resolved_path.parents) > 3:
        root_env = resolved_path.parents[3] / ".env"
    elif len(resolved_path.parents) > 1:
        root_env = resolved_path.parents[1] / ".env"

    if root_env and root_env.exists():
        load_dotenv(root_env, override=False)


_load_env_files()


APP_NAME = os.getenv("APP_NAME", "LimeSurvey RemoteControl 2 Adapter")
ENV = os.getenv("ENV", "dev")
IS_PRODUCTION = ENV.lower() in {"production", "prod"}


def _parse_csv_env(name: str, default: str):
    return [
        item.strip()
        for item in os.getenv(name, default).split(",")
        if item.strip()
    ]


CORS_ORIGINS = _parse_csv_env(
    "CORS_ORIGINS",
    "http://localhost:4200,http://127.0.0.1:4200,http://localhost:8100,http://127.0.0.1:8100",
)

JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "limesurvey-rc2-api")
JWT_TOKEN_TYPE = "service+jwt"


def _optional_service_secret(name: str) -> str:
    """Load one configured issuer secret; keep the old key only as a dev fallback."""
    value = (os.getenv(name) or "").strip()
    if not value and not IS_PRODUCTION:
        value = (os.getenv("JWT_SECRET") or "").strip()
    if value and IS_PRODUCTION and len(value) < 32:
        raise RuntimeError(f"{name} must contain at least 32 characters in production.")
    return value


FORM_BUILDER_SERVICE_JWT_ISSUER = os.getenv(
    "FORM_BUILDER_SERVICE_JWT_ISSUER", "form-builder-server"
)
DICTIONARY_SERVICE_JWT_ISSUER = os.getenv(
    "DICTIONARY_SERVICE_JWT_ISSUER", "limesurvey-dictionary-api"
)
FORM_BUILDER_SERVICE_JWT_SECRET = _optional_service_secret("FORM_BUILDER_SERVICE_JWT_SECRET")
DICTIONARY_SERVICE_JWT_SECRET = _optional_service_secret("DICTIONARY_SERVICE_JWT_SECRET")

if not FORM_BUILDER_SERVICE_JWT_SECRET and not DICTIONARY_SERVICE_JWT_SECRET:
    raise RuntimeError(
        "Configure at least one trusted service JWT secret: "
        "FORM_BUILDER_SERVICE_JWT_SECRET or DICTIONARY_SERVICE_JWT_SECRET."
    )

if (
    IS_PRODUCTION
    and FORM_BUILDER_SERVICE_JWT_SECRET
    and DICTIONARY_SERVICE_JWT_SECRET
    and FORM_BUILDER_SERVICE_JWT_SECRET == DICTIONARY_SERVICE_JWT_SECRET
):
    raise RuntimeError(
        "FORM_BUILDER_SERVICE_JWT_SECRET and DICTIONARY_SERVICE_JWT_SECRET "
        "must be different in production."
    )

JWT_ISSUER_SECRETS = {}
if FORM_BUILDER_SERVICE_JWT_SECRET:
    JWT_ISSUER_SECRETS[FORM_BUILDER_SERVICE_JWT_ISSUER] = FORM_BUILDER_SERVICE_JWT_SECRET
if DICTIONARY_SERVICE_JWT_SECRET:
    JWT_ISSUER_SECRETS[DICTIONARY_SERVICE_JWT_ISSUER] = DICTIONARY_SERVICE_JWT_SECRET

if not IS_PRODUCTION:
    SMOKE_LOCAL_JWT_ISSUER = os.getenv("SMOKE_LOCAL_JWT_ISSUER", "smoke-local")
    SMOKE_LOCAL_JWT_SECRET = (os.getenv("SMOKE_LOCAL_JWT_SECRET") or os.getenv("JWT_SECRET") or "").strip()
    if SMOKE_LOCAL_JWT_SECRET:
        JWT_ISSUER_SECRETS[SMOKE_LOCAL_JWT_ISSUER] = SMOKE_LOCAL_JWT_SECRET

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None
REDIS_USERNAME = os.getenv("REDIS_USERNAME") or None
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_SSL = os.getenv("REDIS_SSL", "false").lower() == "true"
REDIS_SSL_CA_CERTS = os.getenv("REDIS_SSL_CA_CERTS") or None
if IS_PRODUCTION and not REDIS_PASSWORD:
    raise RuntimeError("REDIS_PASSWORD is required in production; a private network alone is not authentication.")
LS_SESSION_TTL_SECONDS = int(os.getenv("LS_SESSION_TTL_SECONDS", "1800"))
ALLOW_IN_MEMORY_STATE = os.getenv(
    "ALLOW_IN_MEMORY_STATE",
    "false" if IS_PRODUCTION else "true",
).lower() == "true"
LS_LOGIN_RATE_LIMIT_PER_MIN = int(os.getenv("LS_LOGIN_RATE_LIMIT_PER_MIN", "8"))

_default_limesurvey_hosts = "localhost,127.0.0.1,host.docker.internal"
if IS_PRODUCTION:
    _default_limesurvey_hosts = ""
ALLOWED_LIMESURVEY_HOSTS = tuple(
    host.lower()
    for host in _parse_csv_env("ALLOWED_LIMESURVEY_HOSTS", _default_limesurvey_hosts)
)
if IS_PRODUCTION and not ALLOWED_LIMESURVEY_HOSTS:
    raise RuntimeError("ALLOWED_LIMESURVEY_HOSTS must contain at least one trusted host in production.")
ALLOW_INSECURE_LIMESURVEY_HTTP = os.getenv(
    "ALLOW_INSECURE_LIMESURVEY_HTTP",
    "true" if not IS_PRODUCTION else "false",
).lower() == "true"

LS_LOGIN_TIMEOUT_SECONDS = float(os.getenv("LS_LOGIN_TIMEOUT_SECONDS", "10"))
LS_SURVEYS_TIMEOUT_SECONDS = float(os.getenv("LS_SURVEYS_TIMEOUT_SECONDS", "10"))
LS_SURVEY_LOAD_TIMEOUT_SECONDS = float(os.getenv("LS_SURVEY_LOAD_TIMEOUT_SECONDS", "120"))
LS_REMOTE_BACKOFF_BASE_SECONDS = float(os.getenv("LS_REMOTE_BACKOFF_BASE_SECONDS", "1"))
LS_REMOTE_BACKOFF_MAX_SECONDS = float(os.getenv("LS_REMOTE_BACKOFF_MAX_SECONDS", "8"))
LS_REMOTE_BACKOFF_JITTER_RATIO = float(os.getenv("LS_REMOTE_BACKOFF_JITTER_RATIO", "0.25"))
LS_ACCOUNT_MAX_CONCURRENT_CALLS = int(os.getenv("LS_ACCOUNT_MAX_CONCURRENT_CALLS", "8"))
LS_ACCOUNT_CONCURRENCY_WAIT_SECONDS = float(os.getenv("LS_ACCOUNT_CONCURRENCY_WAIT_SECONDS", "30"))
LS_ACCOUNT_CONCURRENCY_LEASE_SECONDS = int(os.getenv("LS_ACCOUNT_CONCURRENCY_LEASE_SECONDS", "60"))
LS_RESPONSES_TIMEOUT_SECONDS = float(os.getenv("LS_RESPONSES_TIMEOUT_SECONDS", "60"))
LS_RESPONSES_MAX_BYTES = int(os.getenv("LS_RESPONSES_MAX_BYTES", str(20 * 1024 * 1024)))
LS_RESPONSES_RATE_LIMIT_PER_MIN = int(os.getenv("LS_RESPONSES_RATE_LIMIT_PER_MIN", "12"))
LS_RESPONSES_MAX_FIELDS = int(os.getenv("LS_RESPONSES_MAX_FIELDS", "500"))
LS_REMOTE_CONNECT_TIMEOUT_SECONDS = float(os.getenv("LS_REMOTE_CONNECT_TIMEOUT_SECONDS", "5"))
LS_REMOTE_READ_TIMEOUT_SECONDS = float(os.getenv("LS_REMOTE_READ_TIMEOUT_SECONDS", "30"))
LS_OPTIMIZER_ENABLED = os.getenv("LS_OPTIMIZER_ENABLED", "false").lower() == "true"
LS_OPTIMIZER_TTL_SECONDS = int(os.getenv("LS_OPTIMIZER_TTL_SECONDS", "259200"))
LS_OPTIMIZER_MIN_SUCCESS_RATE = float(os.getenv("LS_OPTIMIZER_MIN_SUCCESS_RATE", "0.95"))
LS_OPTIMIZER_MAX_SAMPLE_QUESTIONS = int(os.getenv("LS_OPTIMIZER_MAX_SAMPLE_QUESTIONS", "10"))
LS_OPTIMIZER_MAX_SURVEYS = int(os.getenv("LS_OPTIMIZER_MAX_SURVEYS", "3"))
LS_OPTIMIZER_MAX_GROUPS = int(os.getenv("LS_OPTIMIZER_MAX_GROUPS", "10"))

# Fallback tuning used when optimizer cache is not populated yet.
DEFAULT_OPTIMAL_PARAMS = {
    "semaphore": 4,
    "maxAttempts": 2,
}
