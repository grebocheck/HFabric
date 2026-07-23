"""SSRF-safe direct-download transport and integrity verification."""

from __future__ import annotations

from ipaddress import ip_address
from pathlib import Path
import socket
from typing import Any
from urllib.parse import urljoin, urlsplit

MB = 1024 * 1024
REDIRECT_CODES = {301, 302, 303, 307, 308}
MAX_DOWNLOAD_REDIRECTS = 5


def assert_public_download_url(url: str) -> None:
    """Reject URL targets that could reach local services or metadata."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Direct downloads require an absolute http(s) URL.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("Credentials embedded in a download URL are not allowed.")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ValueError("The download URL contains an invalid port.") from exc
    hostname = parsed.hostname.rstrip(".")
    if hostname.lower() == "localhost" or hostname.lower().endswith((".localhost", ".local", ".internal")):
        raise ValueError("Downloads from local or private network hosts are blocked.")
    try:
        literal = ip_address(hostname.split("%", 1)[0])
    except ValueError:
        literal = None
    if literal is not None:
        if not literal.is_global:
            raise ValueError("Downloads from local or private network addresses are blocked.")
        return

    try:
        resolved = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except OSError as exc:
        raise ValueError(f"Could not resolve download host {hostname!r}.") from exc
    addresses = {item[4][0].split("%", 1)[0] for item in resolved if item[4]}
    if not addresses or any(not ip_address(address).is_global for address in addresses):
        raise ValueError("The download host resolves to a local or private network address.")


def assert_public_response_peer(response: Any) -> None:
    """Re-check the peer to narrow the DNS-rebinding window."""
    stream = response.extensions.get("network_stream")
    if stream is None or not hasattr(stream, "get_extra_info"):
        return
    peer = stream.get_extra_info("server_addr")
    address = peer[0] if isinstance(peer, tuple) and peer else peer
    if isinstance(address, str) and not ip_address(address.split("%", 1)[0]).is_global:
        raise ValueError("The download connection reached a local or private network address.")


def download_url(
    url: str,
    dest_path: Path,
    headers: dict[str, str] | None = None,
) -> None:
    """Stream a public URL via a part file and validate every redirect."""
    import httpx  # noqa: PLC0415

    temporary = dest_path.with_name(dest_path.name + ".part")
    temporary.unlink(missing_ok=True)
    current_url = url
    original = urlsplit(url)
    original_origin = (
        original.scheme,
        original.hostname,
        original.port,
    )
    request_headers = dict(headers or {})
    timeout = httpx.Timeout(
        connect=30.0,
        read=None,
        write=30.0,
        pool=30.0,
    )
    try:
        with httpx.Client(
            follow_redirects=False,
            timeout=timeout,
            trust_env=False,
        ) as client:
            for redirect_count in range(MAX_DOWNLOAD_REDIRECTS + 1):
                assert_public_download_url(current_url)
                current = urlsplit(current_url)
                current_headers = request_headers
                if (
                    current.scheme,
                    current.hostname,
                    current.port,
                ) != original_origin:
                    current_headers = {
                        key: value
                        for key, value in request_headers.items()
                        if key.lower()
                        not in {
                            "authorization",
                            "cookie",
                            "proxy-authorization",
                        }
                    }
                with client.stream(
                    "GET",
                    current_url,
                    headers=current_headers,
                ) as response:
                    assert_public_response_peer(response)
                    if response.status_code in REDIRECT_CODES:
                        location = response.headers.get("location")
                        if not location:
                            response.raise_for_status()
                        if redirect_count >= MAX_DOWNLOAD_REDIRECTS:
                            raise ValueError("The download exceeded the redirect limit.")
                        current_url = urljoin(
                            current_url,
                            location,
                        )
                        continue
                    response.raise_for_status()
                    with temporary.open("wb") as handle:
                        for chunk in response.iter_bytes(chunk_size=MB):
                            handle.write(chunk)
                    temporary.replace(dest_path)
                    return
        raise ValueError("The download did not produce a file.")
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def verify_sha256(path: Path, expected: str) -> None:
    """Reject and remove a file whose SHA256 does not match."""
    import hashlib  # noqa: PLC0415

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(MB), b""):
            digest.update(chunk)
    actual = digest.hexdigest().lower()
    if actual != expected.lower():
        path.unlink(missing_ok=True)
        raise ValueError(f"SHA256 mismatch (expected {expected[:12]}…, got {actual[:12]}…)")
