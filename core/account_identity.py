"""Create privacy-preserving identifiers for LimeSurvey accounts."""

import hashlib
import json
from typing import Any


def account_cache_id(api: Any) -> str:
    """Hash URL and username so Redis keys remain account-scoped and non-secret."""
    identity = json.dumps(
        {
            "url": str(getattr(api, "url", "")).strip(),
            "username": str(getattr(api, "username", "")).strip(),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
