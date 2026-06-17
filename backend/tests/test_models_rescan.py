from __future__ import annotations

from app.config import settings


async def test_rescan_picks_up_a_new_model_without_restart(app_client):
    """POST /api/models/rescan re-reads the model dirs so a file dropped in after
    startup is usable without a backend restart (P24.8)."""
    before = (await app_client.post("/api/models/rescan")).json()

    new_file = settings.llm_models_dir / "hot-added-llm.gguf"
    new_file.write_bytes(b"GGUF\x00")
    try:
        after = (await app_client.post("/api/models/rescan")).json()
        assert after["llm_models"] == before["llm_models"] + 1
        assert after["models"] == before["models"] + 1

        models = (await app_client.get("/api/models")).json()
        assert any(m["id"] == "hot-added-llm" for m in models)
    finally:
        new_file.unlink(missing_ok=True)
        # Drop it again so the shared temp dir doesn't leak into later tests.
        restored = (await app_client.post("/api/models/rescan")).json()
        assert restored["llm_models"] == before["llm_models"]
