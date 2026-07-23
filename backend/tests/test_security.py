from __future__ import annotations

import logging

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
import pytest
from starlette.testclient import WebSocketDenialResponse

from app.config import settings
from app.main import app
from app.util import request_context, security


async def _async_client(*, client_host: str = "127.0.0.1"):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, client=(client_host, 12345))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_non_loopback_without_token_or_opt_in_fails_before_side_effects(
    monkeypatch,
):
    monkeypatch.setattr(settings, "host", "0.0.0.0")
    monkeypatch.setattr(settings, "api_token", None)
    monkeypatch.setattr(settings, "allow_insecure_lan", False)
    ensure_dirs_called = False

    def ensure_dirs(_settings) -> None:
        nonlocal ensure_dirs_called
        ensure_dirs_called = True

    monkeypatch.setattr(type(settings), "ensure_dirs", ensure_dirs)

    with pytest.raises(RuntimeError, match="Refusing non-loopback"):
        async with app.router.lifespan_context(app):
            pass

    assert ensure_dirs_called is False


async def test_explicit_insecure_lan_opt_in_starts_with_warning(monkeypatch, caplog):
    monkeypatch.setattr(settings, "host", "0.0.0.0")
    monkeypatch.setattr(settings, "api_token", None)
    monkeypatch.setattr(settings, "allow_insecure_lan", True)
    caplog.set_level(logging.WARNING, logger="hfabric")

    async for client in _async_client(client_host="192.168.1.44"):
        response = await client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["security"] == {"exposed": True, "token_required": False}
    assert "SECURITY WARNING" in caplog.text


async def test_bearer_token_auth_keeps_health_open_and_protects_api(monkeypatch):
    monkeypatch.setattr(settings, "host", "127.0.0.1")
    monkeypatch.setattr(settings, "api_token", "secret-token")

    async for client in _async_client():
        health = await client.get("/api/health")
        missing = await client.get("/api/models")
        wrong = await client.get("/api/models", headers={"Authorization": "Bearer nope"})
        ok = await client.get("/api/models", headers={"Authorization": "Bearer secret-token"})

    assert health.status_code == 200
    assert health.json()["security"] == {"exposed": False, "token_required": True}
    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert ok.status_code == 200
    assert missing.json() == {
        "code": "authentication_required",
        "message": "Authentication required",
        "details": None,
        "request_id": missing.headers["X-Request-ID"],
        "detail": "Authentication required",
    }


async def test_configured_token_allows_authenticated_remote_client(monkeypatch):
    monkeypatch.setattr(settings, "host", "0.0.0.0")
    monkeypatch.setattr(settings, "api_token", "secret-token")
    monkeypatch.setattr(settings, "allow_insecure_lan", False)

    async for client in _async_client(client_host="192.168.1.44"):
        health = await client.get("/api/health")
        models = await client.get(
            "/api/models",
            headers={"Authorization": "Bearer secret-token"},
        )

    assert health.status_code == 200
    assert models.status_code == 200


async def test_no_token_preserves_open_loopback_behavior(monkeypatch):
    monkeypatch.setattr(settings, "api_token", None)
    monkeypatch.setattr(settings, "allow_insecure_lan", False)

    async for client in _async_client():
        response = await client.get("/api/models")

    assert response.status_code == 200


async def test_remote_client_is_rejected_across_health_static_and_api(monkeypatch):
    monkeypatch.setattr(settings, "host", "127.0.0.1")
    monkeypatch.setattr(settings, "api_token", None)
    monkeypatch.setattr(settings, "allow_insecure_lan", False)

    async for client in _async_client(client_host="192.168.1.44"):
        health = await client.get("/api/health")
        static = await client.get("/")
        api = await client.get("/api/models")

    assert health.status_code == 403
    assert static.status_code == 403
    assert api.status_code == 403
    assert health.json()["code"] == "remote_forbidden"
    assert health.json()["request_id"] == health.headers["X-Request-ID"]


async def test_request_id_is_preserved_or_replaced_when_invalid(monkeypatch):
    monkeypatch.setattr(settings, "api_token", None)

    async for client in _async_client():
        accepted = await client.get(
            "/api/health",
            headers={"X-Request-ID": "ui.sync-42"},
        )
        replaced = await client.get(
            "/api/health",
            headers={"X-Request-ID": "invalid request id"},
        )

    assert accepted.headers["X-Request-ID"] == "ui.sync-42"
    assert replaced.headers["X-Request-ID"] != "invalid request id"
    assert len(replaced.headers["X-Request-ID"]) == 32
    assert request_context.current_request_id() is None


async def test_validation_errors_follow_the_canonical_error_contract(monkeypatch):
    monkeypatch.setattr(settings, "api_token", None)

    async for client in _async_client():
        response = await client.post(
            "/api/jobs",
            json={"not": "an array"},
            headers={"X-Request-ID": "contract-test"},
        )

    body = response.json()
    assert response.status_code == 422
    assert body["code"] == "validation_error"
    assert body["message"] == "Request validation failed"
    assert body["details"] == body["detail"]
    assert body["request_id"] == "contract-test"


async def test_asset_gets_use_short_lived_cookie_and_reject_query_bearer(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "secret-token")

    async for client in _async_client():
        asset_without_token = await client.get("/api/images/upload/not-a-token")
        asset_with_token = await client.get("/api/images/upload/not-a-token?token=secret-token")
        session = await client.post(
            "/api/auth/asset-session",
            headers={"Authorization": "Bearer secret-token"},
        )
        asset_with_session = await client.get("/api/images/upload/not-a-token")
        write_with_query_token = await client.post("/api/jobs?token=secret-token", json=[])
        regular_api_with_session = await client.get("/api/models")
        logout_with_session = await client.delete("/api/auth/asset-session")
        asset_after_logout = await client.get("/api/images/upload/not-a-token")

    assert asset_without_token.status_code == 401
    assert asset_with_token.status_code == 401
    assert session.status_code == 200
    assert "HttpOnly" in session.headers["set-cookie"]
    assert "SameSite=strict" in session.headers["set-cookie"]
    assert asset_with_session.status_code == 404
    assert write_with_query_token.status_code == 401
    assert regular_api_with_session.status_code == 401
    assert logout_with_session.status_code == 204
    assert asset_after_logout.status_code == 401


def test_websocket_uses_asset_session_cookie_not_query_bearer(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "secret-token")

    with TestClient(app) as client:
        with pytest.raises(WebSocketDenialResponse) as exc:
            with client.websocket_connect("/ws"):
                pass
        assert exc.value.status_code == 401

        rejected_query = None
        try:
            with client.websocket_connect("/ws?token=secret-token"):
                pass
        except WebSocketDenialResponse as exc:
            rejected_query = exc
        assert rejected_query is not None
        assert rejected_query.status_code == 401

        session = client.post(
            "/api/auth/asset-session",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert session.status_code == 200
        with client.websocket_connect("/ws") as ws:
            message = ws.receive_json()

    assert message["type"] == "gpu.status"


def test_asset_session_expires_and_is_invalidated_by_token_rotation(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "old-token")
    value, expires_at = security.create_asset_session(now=1_000)

    assert security.asset_session_matches(value, now=expires_at)
    assert not security.asset_session_matches(value, now=expires_at + 1)

    monkeypatch.setattr(settings, "api_token", "new-token")
    assert not security.asset_session_matches(value, now=1_001)


async def test_reveal_refuses_remote_client_even_with_token(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "secret-token")

    async for client in _async_client(client_host="192.168.1.44"):
        response = await client.post(
            "/api/images/not-real/reveal",
            headers={"Authorization": "Bearer secret-token"},
        )

    assert response.status_code == 403
