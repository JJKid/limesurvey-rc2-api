"""Run one real login/read/logout check against a local limesurvey-rc2-api."""

import argparse
import time

import requests
from jose import jwt


def _authorization_header(args: argparse.Namespace) -> str:
    if args.jwt:
        return args.jwt if args.jwt.startswith("Bearer ") else f"Bearer {args.jwt}"
    token = jwt.encode(
        {
            "sub": "smoke-local",
            "iss": args.jwt_issuer,
            "aud": args.jwt_audience,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
        },
        args.jwt_secret,
        algorithm="HS256",
        headers={"typ": "service+jwt"},
    )
    return f"Bearer {token}"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", required=True, help="LS RC2 endpoint")
    p.add_argument("--user", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--api", default="http://127.0.0.1:8000", help="limesurvey-rc2-api base URL")
    p.add_argument("--sid", type=int, required=True)
    p.add_argument("--language")
    auth = p.add_mutually_exclusive_group(required=True)
    auth.add_argument("--jwt", help="Existing JWT, with or without the Bearer prefix")
    auth.add_argument("--jwt-secret", help="SMOKE_LOCAL_JWT_SECRET used to create a five-minute service token")
    p.add_argument("--jwt-issuer", default="smoke-local", help="Configured development smoke-token issuer")
    p.add_argument("--jwt-audience", default="limesurvey-rc2-api", help="Audience expected by limesurvey-rc2-api")
    args = p.parse_args()

    auth_headers = {"Authorization": _authorization_header(args)}
    session_key = None

    try:
        login = requests.post(
            f"{args.api}/login-limesurvey",
            json={"url": args.url, "username": args.user, "password": args.password},
            headers=auth_headers,
            timeout=15,
        )
        login.raise_for_status()
        session_key = login.json()["session_key"]
        session_headers = {
            **auth_headers,
            "X-LimeSurvey-Session": session_key,
        }
        print("Local session UUID:", session_key)

        surveys = requests.get(
            f"{args.api}/surveys",
            headers=session_headers,
            timeout=15,
        )
        surveys.raise_for_status()
        survey_rows = surveys.json()
        print("Visible surveys:", len(survey_rows))
        print("First surveys:", survey_rows[:2])

        query = {"language": args.language} if args.language else None
        structure = requests.get(
            f"{args.api}/survey_structure/{args.sid}",
            params=query,
            headers=session_headers,
            timeout=60,
        )
        structure.raise_for_status()
        result = structure.json()
        survey = result["survey"]
        print("SurveyStructure:", {
            "id": survey.get("id"),
            "title": survey.get("title"),
            "language": survey.get("language"),
            "groups": len(survey.get("groups", [])),
            "fields": len(survey.get("fields", [])),
            "issues": len(result.get("issues", [])),
        })
    finally:
        if session_key:
            logout = requests.get(
                f"{args.api}/logout-limesurvey",
                headers={**auth_headers, "X-LimeSurvey-Session": session_key},
                timeout=15,
            )
            print("Logout status:", logout.status_code)

if __name__ == "__main__":
    main()
