from pathlib import Path
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

@pytest.fixture(scope="session")
def client():
    with TestClient(app) as c:
        yield c

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
