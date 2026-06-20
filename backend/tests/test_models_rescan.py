from __future__ import annotations

import json
import struct

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


async def test_rescan_classifies_a_hot_added_anima_checkpoint(app_client):
    before = (await app_client.post("/api/models/rescan")).json()
    path = settings.image_models_dir / "hot-added-anima.safetensors"
    keys = [
        "net.blocks.0.self_attn.q_proj.weight",
        "net.llm_adapter.embed.weight",
        "net.x_embedder.proj.1.weight",
    ]
    header = {
        key: {"dtype": "F16", "shape": [1], "data_offsets": [index * 2, index * 2 + 2]}
        for index, key in enumerate(keys)
    }
    blob = json.dumps(header).encode("utf-8")
    with path.open("wb") as file:
        file.write(struct.pack("<Q", len(blob)))
        file.write(blob)
        file.write(b"\x00" * (len(keys) * 2))
    try:
        after = (await app_client.post("/api/models/rescan")).json()
        assert after["image_models"] == before["image_models"] + 1
        models = (await app_client.get("/api/models")).json()
        anima = next(model for model in models if model["id"] == "hot-added-anima")
        assert anima["family"] == "anima"
    finally:
        path.unlink(missing_ok=True)
        await app_client.post("/api/models/rescan")
