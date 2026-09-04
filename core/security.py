"""Authenticate service-to-service requests received by this adapter."""

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

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
            raise JWTError("JWT type is not accepted")
        unverified = jwt.get_unverified_claims(token)
        issuer = str(unverified.get("iss") or "")
        secret = JWT_ISSUER_SECRETS.get(issuer)
        if not secret:
            raise JWTError("JWT issuer is not trusted")
        claims = jwt.decode(
            token,
            secret,
            algorithms=[JWT_ALGORITHM],
            audience=JWT_AUDIENCE,
            issuer=issuer,
            options={
                "require_aud": True,
                "require_exp": True,
                "require_iat": True,
                "require_iss": True,
                "require_sub": True,
            },
        )
        subject = str(claims.get("sub") or "").strip()
        if not subject:
            raise JWTError("JWT subject is missing")
    except JWTError:
        raise HTTPException(status_code=401, detail="Internal service token is invalid or expired")

    return AuthenticatedIdentity(subject=subject, issuer=issuer)
