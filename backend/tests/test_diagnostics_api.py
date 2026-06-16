from __future__ import annotations

import io
import json
import zipfile

from app.api import diagnostics


def test_scrub_mapping_redacts_secret_keys():
    scrubbed = diagnostics._scrub_mapping(
        {
            "api_token": "secret123",
            "nested": {"password": "x", "ok": "keep"},
            "list": [{"apiKey": "y"}, "plain"],
            "ok": "keep",
        }
    )
    assert scrubbed["api_token"] == diagnostics._REDACTED
    assert scrubbed["nested"]["password"] == diagnostics._REDACTED
    assert scrubbed["nested"]["ok"] == "keep"
    assert scrubbed["list"][0]["apiKey"] == diagnostics._REDACTED
    assert scrubbed["list"][1] == "plain"
    assert scrubbed["ok"] == "keep"


def test_scrub_text_redacts_configured_token(monkeypatch):
    monkeypatch.setattr(diagnostics.settings, "api_token", "tok-xyz")
    assert "tok-xyz" not in diagnostics._scrub_text("auth: tok-xyz here")
    assert diagnostics._REDACTED in diagnostics._scrub_text("auth: tok-xyz here")


def test_scrub_text_noop_when_no_token(monkeypatch):
    monkeypatch.setattr(diagnostics.settings, "api_token", None)
    assert diagnostics._scrub_text("nothing to redact") == "nothing to redact"


async def test_export_diagnostics_returns_zip_bundle(app_client):
    res = await app_client.get("/api/diagnostics/export")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/zip")

    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        names = set(zf.namelist())
        assert {"manifest.json", "health.json", "settings.json"} <= names
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["app_version"]
        assert "platform" in manifest
        # logs dir may be empty in tests; either real logs or the placeholder is present.
        assert any(n.startswith("logs/") for n in names)


async def test_export_diagnostics_scrubs_api_token(app_client, monkeypatch):
    # With a token configured the endpoint requires auth (middleware) — send it, then
    # confirm the bundle never leaks the token back out.
    monkeypatch.setattr(diagnostics.settings, "api_token", "super-secret-token")
    res = await app_client.get(
        "/api/diagnostics/export",
        headers={"Authorization": "Bearer super-secret-token"},
    )
    assert res.status_code == 200
    with zipfile.ZipFile(io.BytesIO(res.content)) as zf:
        settings_blob = zf.read("settings.json").decode("utf-8")
    assert "super-secret-token" not in settings_blob
