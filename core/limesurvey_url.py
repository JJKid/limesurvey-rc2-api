"""Validate user-provided LimeSurvey RemoteControl endpoints before connecting."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from core.config import ALLOWED_LIMESURVEY_HOSTS, ALLOW_INSECURE_LIMESURVEY_HTTP


class LimeSurveyUrlPolicyError(ValueError):
    """Raised when a RemoteControl URL violates the outbound connection policy."""


def validate_limesurvey_url(
    value: str,
    *,
    allowed_hosts: tuple[str, ...] = ALLOWED_LIMESURVEY_HOSTS,
    allow_insecure_http: bool = ALLOW_INSECURE_LIMESURVEY_HTTP,
) -> str:
    """Return a normalized trusted RemoteControl URL or reject it before I/O."""
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"}:
        raise LimeSurveyUrlPolicyError("LimeSurvey URL must use HTTP or HTTPS.")
    if parsed.scheme == "http" and not allow_insecure_http:
        raise LimeSurveyUrlPolicyError("LimeSurvey URL must use HTTPS.")
    if parsed.username or parsed.password:
        raise LimeSurveyUrlPolicyError("Credentials must not be embedded in the LimeSurvey URL.")
    if parsed.fragment:
        raise LimeSurveyUrlPolicyError("LimeSurvey URL must not contain a fragment.")
    if not parsed.hostname:
        raise LimeSurveyUrlPolicyError("LimeSurvey URL must contain a hostname.")

    normalized_path = parsed.path.rstrip("/")
    if not normalized_path.endswith("/admin/remotecontrol"):
        raise LimeSurveyUrlPolicyError(
            "LimeSurvey URL must point to the RemoteControl endpoint ending in /admin/remotecontrol."
        )

    hostname = parsed.hostname.lower().rstrip(".")
    trusted_hosts = {host.lower().rstrip(".") for host in allowed_hosts}
    local_aliases = {"localhost", "127.0.0.1", "host.docker.internal"}
    explicitly_allowed = hostname in trusted_hosts or (
        hostname in local_aliases and bool(local_aliases & trusted_hosts)
    )
    if trusted_hosts and not explicitly_allowed:
        raise LimeSurveyUrlPolicyError(f'LimeSurvey host "{hostname}" is not allowed.')
    if not trusted_hosts:
        _reject_non_public_destination(hostname, parsed.port)

    netloc = hostname
    if parsed.port:
        netloc = f"{hostname}:{parsed.port}"
    return urlunsplit((parsed.scheme, netloc, normalized_path, parsed.query, ""))


def _reject_non_public_destination(hostname: str, port: int | None) -> None:
    """Reject addresses that could expose local infrastructure through SSRF."""
    try:
        addresses = {
            entry[4][0]
            for entry in socket.getaddrinfo(hostname, port or 443, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise LimeSurveyUrlPolicyError("LimeSurvey hostname could not be resolved.") from exc

    if not addresses:
        raise LimeSurveyUrlPolicyError("LimeSurvey hostname did not resolve to an address.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global:
            raise LimeSurveyUrlPolicyError(
                "LimeSurvey host resolves to a private or local address that is not explicitly allowed."
            )
