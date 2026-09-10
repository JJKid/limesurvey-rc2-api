from pathlib import Path
import os
import sys

import pytest
from fastapi.testclient import TestClient
from jose import jwt

# Ensure /app (repo root inside container) is importable when pytest starts from /app/tests.
TESTS_DIR = Path(__file__).resolve().parent
PROJECT_DIR = TESTS_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from app import app
from core.config import (
    FORM_BUILDER_SERVICE_JWT_ISSUER,
    FORM_BUILDER_SERVICE_JWT_SECRET,
    JWT_ALGORITHM,
    JWT_AUDIENCE,
    JWT_TOKEN_TYPE,
)

@pytest.fixture
def client():
    # HTTP unit tests mock their collaborators. Do not open the developer's Redis
    # or start the real session reaper; asyncio.run tests also use separate loops.
    # Startup/shutdown and real services require explicit integration tests.
    client = TestClient(app)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def integration_client():
    """Start real Redis and lifecycle hooks only for explicitly configured LS tests."""
    required = ("LS_INTEGRATION_URL", "LS_INTEGRATION_USERNAME", "LS_INTEGRATION_PASSWORD", "LS_INTEGRATION_SID")
    if any(not os.getenv(name) for name in required):
        pytest.skip("Configure LS_INTEGRATION_URL, USERNAME, PASSWORD and SID for real integration.")
    with TestClient(app) as client:
        yield client

@pytest.fixture
def auth_headers():
    """
    Build a valid Authorization header using the same secret/algorithm as app.
    """
    token = jwt.encode(
        {
            "sub": "pytest-user",
            "iss": FORM_BUILDER_SERVICE_JWT_ISSUER,
            "aud": JWT_AUDIENCE,
            "iat": int(__import__("time").time()),
            "exp": int(__import__("time").time()) + 60,
        },
        FORM_BUILDER_SERVICE_JWT_SECRET,
        algorithm=JWT_ALGORITHM,
        headers={"typ": JWT_TOKEN_TYPE},
    )
    return {"Authorization": f"Bearer {token}"}
