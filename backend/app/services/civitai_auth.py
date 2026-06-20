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

import json
from typing import Any

from ..config import settings

_KEY = "civitai_api_key"
_COOKIE = "civitai_session_cookie"
# CivitAI's NextAuth session cookie. Reusable for downloads now and for the
# future image-upload flow (it acts on behalf of the logged-in account).
_COOKIE_NAME = "__Secure-civitai-token"
_UA = "ImageFabric/CivitAI"


def _secrets_path():
    return settings.data_dir / "secrets.json"


def _load() -> dict[str, Any]:
    path = _secrets_path()
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _save(data: dict[str, Any]) -> None:
    path = _secrets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:  # best-effort tightening; a no-op on Windows
        path.chmod(0o600)
    except OSError:
        pass


def get_key() -> str | None:
    value = str(_load().get(_KEY) or "").strip()
    return value or None


def has_key() -> bool:
    return get_key() is not None


def set_key(api_key: str) -> None:
    clean = (api_key or "").strip()
    data = _load()
    if clean:
        data[_KEY] = clean
    else:
        data.pop(_KEY, None)
    _save(data)


def clear_key() -> None:
    data = _load()
    if data.pop(_KEY, None) is not None:
        _save(data)


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
    data = _load()
    if value:
        data[_COOKIE] = value
    else:
        data.pop(_COOKIE, None)
    _save(data)


def clear_cookie() -> None:
    data = _load()
    if data.pop(_COOKIE, None) is not None:
        _save(data)


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
