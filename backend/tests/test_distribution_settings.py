from __future__ import annotations

import json

from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.main import app


async def _client():
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


async def test_prod_serving_mode_serves_tmp_dist_and_keeps_health(monkeypatch, tmp_path):
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><div id='root'>ok</div>", encoding="utf-8")
    (assets / "index-abc123.js").write_text("console.log('ok')", encoding="utf-8")

    monkeypatch.setattr(settings, "serve_frontend", True)
    monkeypatch.setattr(settings, "frontend_dist_dir", dist)

    async for client in _client():
        home = await client.get("/")
        spa = await client.get("/workspace/images")
        asset = await client.get("/assets/index-abc123.js")
        health = await client.get("/api/health")

    assert home.status_code == 200
    assert "id='root'" in home.text
    assert home.headers["cache-control"] == "no-cache"
    assert spa.status_code == 200
    assert asset.status_code == 200
    assert "max-age=31536000" in asset.headers["cache-control"]
    assert health.status_code == 200
    assert health.json()["status"] == "ok"


async def test_settings_overrides_get_put_validation_and_persistence(
    monkeypatch,
    isolated_runtime,
):
    monkeypatch.setattr(settings, "default_steps", 28)
    monkeypatch.setattr(settings, "default_guidance", 3.5)
    monkeypatch.setattr(settings, "default_width", 1024)
    monkeypatch.setattr(settings, "default_height", 1024)
    monkeypatch.setattr(settings, "keep_warm_models", False)
    monkeypatch.setattr(settings, "keep_warm_max_models", 1)

    async for client in _client():
        current = (await client.get("/api/settings/overrides")).json()
        updated = await client.put(
            "/api/settings/overrides",
            json={
                "default_steps": 999,
                "default_guidance": 4.25,
                "default_width": 777,
                "default_height": 2049,
                "keep_warm_models": True,
                "keep_warm_max_models": 3,
                "min_free_ram_gb": 0,
            },
        )
        rejected = await client.put("/api/settings/overrides", json={"host": "0.0.0.0"})
        roundtrip = (await client.get("/api/settings/overrides")).json()

    assert current["values"]["default_steps"] == 28
    assert updated.status_code == 200
    values = updated.json()["values"]
    assert values["default_steps"] == 150
    assert values["default_guidance"] == 4.25
    assert values["default_width"] == 768
    assert values["default_height"] == 2048
    assert values["keep_warm_models"] is True
    assert values["keep_warm_max_models"] == 3
    assert values["min_free_ram_gb"] == 0.5
    assert rejected.status_code == 422
    assert "host" in rejected.text
    assert roundtrip["values"] == values

    path = isolated_runtime["data_dir"] / "settings-overrides.json"
    assert json.loads(path.read_text(encoding="utf-8")) == values
