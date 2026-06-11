from __future__ import annotations

import logging

from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient
import pytest
from starlette.testclient import WebSocketDenialResponse

from app.config import settings
from app.main import app


async def _async_client(*, client_host: str = "127.0.0.1"):
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app, client=(client_host, 12345))
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_health_reports_exposed_posture_and_startup_warning(monkeypatch, caplog):
    monkeypatch.setattr(settings, "host", "0.0.0.0")
    monkeypatch.setattr(settings, "api_token", None)
    caplog.set_level(logging.WARNING, logger="hfabric")

    async for client in _async_client():
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


async def test_no_token_preserves_open_loopback_behavior(monkeypatch):
    monkeypatch.setattr(settings, "api_token", None)

    async for client in _async_client():
        response = await client.get("/api/models")

    assert response.status_code == 200


async def test_asset_gets_accept_query_token_but_writes_do_not(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "secret-token")

    async for client in _async_client():
        asset_without_token = await client.get("/api/images/upload/not-a-token")
        asset_with_token = await client.get("/api/images/upload/not-a-token?token=secret-token")
        write_with_query_token = await client.post("/api/jobs?token=secret-token", json=[])

    assert asset_without_token.status_code == 401
    assert asset_with_token.status_code == 404
    assert write_with_query_token.status_code == 401


def test_websocket_requires_query_token(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "secret-token")

    with TestClient(app) as client:
        with pytest.raises(WebSocketDenialResponse) as exc:
            with client.websocket_connect("/ws"):
                pass
        assert exc.value.status_code == 401

        with client.websocket_connect("/ws?token=secret-token") as ws:
            message = ws.receive_json()

    assert message["type"] == "gpu.status"


async def test_reveal_refuses_remote_client_even_with_token(monkeypatch):
    monkeypatch.setattr(settings, "api_token", "secret-token")

    async for client in _async_client(client_host="192.168.1.44"):
        response = await client.post(
            "/api/images/not-real/reveal",
            headers={"Authorization": "Bearer secret-token"},
        )

    assert response.status_code == 403
