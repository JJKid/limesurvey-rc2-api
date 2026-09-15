"""Authenticate service-to-service requests received by this adapter."""

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt import InvalidTokenError

from core.config import (
    JWT_ALGORITHM,
    JWT_AUDIENCE,
    JWT_ISSUER_SECRETS,
    JWT_TOKEN_TYPE,
)


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """Verified identity of the internal service making the request."""

    subject: str
    issuer: str


internal_service_bearer = HTTPBearer(
    auto_error=False,
    scheme_name="InternalServiceJWT",
    description=(
        "Short-lived service JWT issued by form-builder-server or "
        "limesurvey-dictionary-api. Browser authentication cookies are not accepted."
    ),
)


def verify_token(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(internal_service_bearer),
) -> AuthenticatedIdentity:
    """Validate a short-lived internal JWT and return its trusted identity.

    Browser cookies are deliberately not accepted here. NestJS authenticates
    the browser first and then emits its own short-lived service token.
    """
    token = (
        credentials.credentials.strip()
        if credentials and credentials.scheme.casefold() == "bearer"
        else None
    )

    if not token:
        raise HTTPException(status_code=401, detail="Internal service token is missing")

    try:
        header = jwt.get_unverified_header(token)
        if header.get("typ") != JWT_TOKEN_TYPE:
            raise InvalidTokenError("JWT type is not accepted")
        # Unverified iss selects a configured key only; trust starts after decode.
        unverified = jwt.decode(token, options={"verify_signature": False})
        issuer = str(unverified.get("iss") or "")
        secret = JWT_ISSUER_SECRETS.get(issuer)
        if not secret:
            raise InvalidTokenError("JWT issuer is not trusted")
        claims = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            issuer=issuer,
            options={
                "require": ["aud", "exp", "iat", "iss", "sub"],
            },
        )
        subject = str(claims.get("sub") or "").strip()
        if not subject:
            raise InvalidTokenError("JWT subject is missing")
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Internal service token is invalid or expired")

    return AuthenticatedIdentity(subject=subject, issuer=issuer)
