"""CivitAI account secret store (Phase C).

Stores an optional CivitAI API key in ``data/secrets.json`` (the ``data/`` folder is
gitignored and local-only) so gated / early-access models can be downloaded and
region-restricted metadata is visible. The key is never returned to the client —
only whether one is set and whether it verifies against CivitAI. Setting the key is
restricted to loopback callers at the API layer, consistent with the project's
env-only auth posture (see ``settings_overrides`` which keeps auth out of the plain
settings file).
"""

from __future__ import annotations

from typing import Any

from ..config import settings
from .atomic_json import AtomicJSONStore

_KEY = "civitai_api_key"
_COOKIE = "civitai_session_cookie"
_SCHEMA = "hfabric.local-secrets"
SECRET_STORAGE_DECISION = {
    "format": "local-json",
    "redaction": "values-never-exposed",
    "backups": False,
    "posix_permissions": "0600",
    "windows": (
        "inherit the data-directory ACL; DPAPI/keyring are intentionally not used "
        "so unattended startup and portable backup/restore keep working"
    ),
}
# CivitAI's NextAuth session cookie. Reusable for downloads now and for the
# future image-upload flow (it acts on behalf of the logged-in account).
_COOKIE_NAME = "__Secure-civitai-token"
_UA = "ImageFabric/CivitAI"


def _secrets_path():
    return settings.data_dir / "secrets.json"


def _store() -> AtomicJSONStore:
    # The on-disk store is deliberately local and permission-restricted. Values
    # are never included in API/diagnostics payloads. Native keyring/DPAPI is not
    # used because this file must remain available to unattended local startup.
    return AtomicJSONStore(
        _secrets_path(),
        schema=_SCHEMA,
        max_bytes=256 * 1024,
        mode=0o600,
        backup=False,
    )


def _validate(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("local secrets must be a JSON object")
    return dict(raw)


def _load() -> dict[str, Any]:
    return _store().read({}, validator=_validate)


def _update(mutator) -> dict[str, Any]:
    return _store().update({}, mutator, validator=_validate)


def redacted_status() -> dict[str, Any]:
    """Safe storage posture for diagnostics; credential values never leave here."""
    data = _load()
    return {
        "api_key": "<redacted>" if data.get(_KEY) else None,
        "session_cookie": "<redacted>" if data.get(_COOKIE) else None,
        "storage": "atomic-user-file",
        "protection": dict(SECRET_STORAGE_DECISION),
    }


def get_key() -> str | None:
    value = str(_load().get(_KEY) or "").strip()
    return value or None


def has_key() -> bool:
    return get_key() is not None


def set_key(api_key: str) -> None:
    clean = (api_key or "").strip()

    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        if clean:
            data[_KEY] = clean
        else:
            data.pop(_KEY, None)
        return data

    _update(mutate)


def clear_key() -> None:
    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        data.pop(_KEY, None)
        return data

    _update(mutate)


# --------------------------------------------------------------------------- #
# Session cookie (native account login, reused for upload later)
# --------------------------------------------------------------------------- #
def _normalize_cookie(raw: str) -> str:
    """Accept either the bare ``__Secure-civitai-token`` value or a pasted cookie
    string (``name=value; other=…``) and return just our token's value."""
    s = (raw or "").strip()
    if not s:
        return ""
    if f"{_COOKIE_NAME}=" in s:
        s = s.split(f"{_COOKIE_NAME}=", 1)[1].split(";", 1)[0].strip()
    return s


def get_cookie() -> str | None:
    value = str(_load().get(_COOKIE) or "").strip()
    return value or None


def has_cookie() -> bool:
    return get_cookie() is not None


def set_cookie(raw: str) -> None:
    value = _normalize_cookie(raw)

    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        if value:
            data[_COOKIE] = value
        else:
            data.pop(_COOKIE, None)
        return data

    _update(mutate)


def clear_cookie() -> None:
    def mutate(data: dict[str, Any]) -> dict[str, Any]:
        data.pop(_COOKIE, None)
        return data

    _update(mutate)


# --------------------------------------------------------------------------- #
# Auth resolution (API key preferred for download/browse; cookie as fallback)
# --------------------------------------------------------------------------- #
def auth_headers() -> dict[str, str]:
    """Headers to authenticate a browse/API request, or ``{}`` for anonymous."""
    key = get_key()
    if key:
        return {"Authorization": f"Bearer {key}"}
    cookie = get_cookie()
    if cookie:
        return {"Cookie": f"{_COOKIE_NAME}={cookie}"}
    return {}


def download_auth(url: str) -> tuple[str, dict[str, str] | None]:
    """Return (url, headers) for a CivitAI file download. The download endpoint
    authenticates via ``?token=`` for an API key (and accepts a bearer header);
    a session cookie authenticates via the ``Cookie`` header."""
    key = get_key()
    if key:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}token={key}", {"Authorization": f"Bearer {key}"}
    cookie = get_cookie()
    if cookie:
        return url, {"Cookie": f"{_COOKIE_NAME}={cookie}"}
    return url, None


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #
def _verify_with_headers(headers: dict[str, str]) -> dict[str, Any]:
    """Best-effort: hit an auth-tied filter (``favorites``) and treat 401/403 as a
    bad credential. CivitAI has no public ``whoami`` so we cannot return a username."""
    import httpx  # noqa: PLC0415

    try:
        with httpx.Client(
            base_url="https://civitai.com/api/v1",
            headers={**headers, "User-Agent": _UA},
            timeout=20.0,
        ) as client:
            resp = client.get("/models", params={"limit": 1, "favorites": "true"})
    except Exception as exc:  # noqa: BLE001 - any network failure becomes a clean message
        return {"verified": False, "reason": f"Could not reach CivitAI: {type(exc).__name__}"}

    if resp.status_code in (401, 403):
        return {"verified": False, "reason": "CivitAI rejected the credential."}
    if resp.status_code >= 400:
        return {"verified": False, "reason": f"CivitAI returned HTTP {resp.status_code}."}
    return {"verified": True, "reason": None}


def verify_key(api_key: str | None = None) -> dict[str, Any]:
    key = (api_key if api_key is not None else get_key() or "").strip()
    if not key:
        return {"verified": False, "reason": "No API key is set."}
    return _verify_with_headers({"Authorization": f"Bearer {key}"})


def verify_cookie(cookie: str | None = None) -> dict[str, Any]:
    value = _normalize_cookie(cookie) if cookie is not None else (get_cookie() or "")
    if not value:
        return {"verified": False, "reason": "No session cookie is set."}
    return _verify_with_headers({"Cookie": f"{_COOKIE_NAME}={value}"})


# Backwards-compatible alias.
verify = verify_key
