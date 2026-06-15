"""Security posture and API-token helpers."""

from __future__ import annotations

import hmac
from ipaddress import ip_address
import logging

from fastapi import Request, WebSocket

from ..config import settings

ASSET_TOKEN_PREFIXES = (
    "/api/chat/uploads/",
    "/api/images/",
    "/api/tts/audio/",
    "/api/voice/engine/file/",
)


def configured_api_token() -> str | None:
    token = (settings.api_token or "").strip()
    return token or None


def api_token_required() -> bool:
    return configured_api_token() is not None


def token_matches(candidate: str | None) -> bool:
    token = configured_api_token()
    return token is None or (
        isinstance(candidate, str)
        and bool(candidate)
        and hmac.compare_digest(candidate, token)
    )


def _is_loopback_name(host: str) -> bool:
    return host.lower() in {"localhost", "localhost.localdomain"}


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    value = host.strip().strip("[]")
    if "%" in value:
        value = value.split("%", 1)[0]
    if _is_loopback_name(value):
        return True
    try:
        return ip_address(value).is_loopback
    except ValueError:
        return False


def is_exposed_bind(host: str | None = None) -> bool:
    value = (host if host is not None else settings.host).strip()
    if not value:
        return False
    if is_loopback_host(value):
        return False
    try:
        return not ip_address(value.strip("[]")).is_loopback
    except ValueError:
        # Hostnames other than localhost can resolve to non-loopback addresses.
        return True


def security_posture() -> dict[str, bool]:
    return {
        "exposed": is_exposed_bind(),
        "token_required": api_token_required(),
    }


def log_startup_posture(logger: logging.Logger) -> None:
    posture = security_posture()
    if posture["exposed"] and not posture["token_required"]:
        logger.warning(
            "SECURITY WARNING: HFabric is bound to %s:%s without HFAB_API_TOKEN; "
            "LAN clients can reach the API. Bind to 127.0.0.1 or set HFAB_API_TOKEN.",
            settings.host,
            settings.port,
        )


def _bearer_token(headers) -> str | None:
    auth = headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()


def _query_token_allowed(request: Request) -> bool:
    if request.method not in {"GET", "HEAD"}:
        return False
    return any(request.url.path.startswith(prefix) for prefix in ASSET_TOKEN_PREFIXES)


def request_is_authorized(request: Request) -> bool:
    if not api_token_required():
        return True
    if token_matches(_bearer_token(request.headers)):
        return True
    return _query_token_allowed(request) and token_matches(request.query_params.get("token"))


def websocket_is_authorized(ws: WebSocket) -> bool:
    return not api_token_required() or token_matches(ws.query_params.get("token"))
