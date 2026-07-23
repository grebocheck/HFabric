"""Security posture and API-token helpers."""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

from fastapi import Request, WebSocket

from ..config import settings
from .network_policy import is_exposed_bind, is_loopback_host, require_secure_bind

ASSET_TOKEN_PREFIXES = (
    "/api/chat/uploads/",
    "/api/diagnostics/",
    "/api/images/",
    "/api/tts/audio/",
    "/api/videos/",
    "/api/voice/engine/file/",
)
ASSET_SESSION_COOKIE = "hfabric_asset_session"
ASSET_SESSION_TTL_SECONDS = 10 * 60


def configured_api_token() -> str | None:
    token = (settings.api_token or "").strip()
    return token or None


def api_token_required() -> bool:
    return configured_api_token() is not None


def insecure_lan_allowed() -> bool:
    return bool(settings.allow_insecure_lan)


def token_matches(candidate: str | None) -> bool:
    token = configured_api_token()
    return token is None or (
        isinstance(candidate, str)
        and bool(candidate)
        and hmac.compare_digest(candidate, token)
    )


def create_asset_session(*, now: int | None = None) -> tuple[str, int]:
    """Create a short-lived, bearer-free browser session for media requests."""

    token = configured_api_token()
    if token is None:
        raise RuntimeError("an API token is not configured")
    expires_at = (int(time.time()) if now is None else now) + ASSET_SESSION_TTL_SECONDS
    payload = f"asset:{expires_at}"
    signature = hmac.new(
        token.encode("utf-8"),
        payload.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{expires_at}.{signature}", expires_at


def asset_session_matches(candidate: str | None, *, now: int | None = None) -> bool:
    """Validate an asset session without ever placing the bearer in a URL."""

    token = configured_api_token()
    if token is None:
        return True
    if not candidate:
        return False
    expires_raw, separator, supplied_signature = candidate.partition(".")
    if not separator or not expires_raw.isascii() or not expires_raw.isdigit():
        return False
    expires_at = int(expires_raw)
    current_time = int(time.time()) if now is None else now
    if expires_at < current_time or expires_at > current_time + ASSET_SESSION_TTL_SECONDS:
        return False
    expected = hmac.new(
        token.encode("utf-8"),
        f"asset:{expires_at}".encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(supplied_signature, expected)


def security_posture() -> dict[str, bool]:
    return {
        "exposed": is_exposed_bind(settings.host),
        "token_required": api_token_required(),
    }


def enforce_startup_posture() -> None:
    """Reject an explicitly exposed, unauthenticated configuration by default."""

    try:
        require_secure_bind(
            settings.host,
            configured_api_token(),
            insecure_lan_allowed(),
        )
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc


def log_startup_posture(logger: logging.Logger) -> None:
    posture = security_posture()
    if posture["exposed"] and not posture["token_required"]:
        logger.warning(
            "SECURITY WARNING: explicit insecure LAN opt-in active at %s:%s "
            "without HFAB_API_TOKEN; LAN clients can reach the API.",
            settings.host,
            settings.port,
        )


def _bearer_token(headers) -> str | None:
    auth = headers.get("authorization", "")
    scheme, _, value = auth.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None
    return value.strip()


def _asset_session_allowed(request: Request) -> bool:
    if request.method not in {"GET", "HEAD"}:
        return False
    return any(request.url.path.startswith(prefix) for prefix in ASSET_TOKEN_PREFIXES)


def _asset_session_logout_allowed(request: Request) -> bool:
    return (
        request.method == "DELETE"
        and request.url.path == "/api/auth/asset-session"
    )


def remote_client_allowed(host: str | None) -> bool:
    """Protect against a uvicorn ``--host`` that differs from ``settings.host``."""

    return api_token_required() or insecure_lan_allowed() or is_loopback_host(host)


def request_is_authorized(request: Request) -> bool:
    client_host = request.client.host if request.client else None
    if not remote_client_allowed(client_host):
        return False
    if not api_token_required():
        return True
    if token_matches(_bearer_token(request.headers)):
        return True
    session_valid = asset_session_matches(request.cookies.get(ASSET_SESSION_COOKIE))
    return (
        (_asset_session_allowed(request) or _asset_session_logout_allowed(request))
        and session_valid
    )


def websocket_is_authorized(ws: WebSocket) -> bool:
    client_host = ws.client.host if ws.client else None
    if not remote_client_allowed(client_host):
        return False
    if not api_token_required():
        return True
    return asset_session_matches(ws.cookies.get(ASSET_SESSION_COOKIE))
