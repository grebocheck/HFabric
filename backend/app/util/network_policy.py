"""Dependency-free network exposure policy shared by app and launchers."""

from __future__ import annotations

from ipaddress import ip_address


class NetworkPostureError(ValueError):
    pass


def is_loopback_host(host: str | None) -> bool:
    if not host:
        return False
    value = host.strip().strip("[]")
    if "%" in value:
        value = value.split("%", 1)[0]
    if value.lower() in {"localhost", "localhost.localdomain"}:
        return True
    try:
        return ip_address(value).is_loopback
    except ValueError:
        return False


def is_exposed_bind(host: str | None) -> bool:
    return bool((host or "").strip()) and not is_loopback_host(host)


def require_secure_bind(
    host: str | None,
    api_token: str | None,
    allow_insecure_lan: bool,
) -> bool:
    """Return whether explicit insecure LAN mode is active, or reject the bind."""

    exposed = is_exposed_bind(host)
    has_token = bool((api_token or "").strip())
    insecure = exposed and not has_token
    if insecure and not allow_insecure_lan:
        raise NetworkPostureError(
            f"Refusing non-loopback HFAB_HOST {host!r} without HFAB_API_TOKEN. "
            "Set a bearer token, bind to 127.0.0.1, or deliberately set "
            "HFAB_ALLOW_INSECURE_LAN=true for an isolated trusted network."
        )
    return insecure
