from __future__ import annotations

from app.db.session import session_scope
from app.services import model_profile_service as mps
from app.util import sysmon


async def test_model_profile_api_lists_resets_one_and_clears_all(app_client):
    async with session_scope() as s:
        await mps.record(
            s,
            model_id="stub-sdxl",
            family="sdxl",
            quant=None,
            ram_gb=5.5,
            vram_gb=6.25,
        )
    sysmon.set_learned_profile("stub-sdxl", ram_gb=5.5, vram_gb=6.25)

    listed = (await app_client.get("/api/models/profiles")).json()
    assert listed[0]["model_id"] == "stub-sdxl"
    assert listed[0]["model"] == "stub-sdxl"
    assert listed[0]["ram_gb"] == 5.5
    assert listed[0]["vram_gb"] == 6.25

    reset = await app_client.delete("/api/models/profiles/stub-sdxl")
    assert reset.status_code == 200
    assert reset.json() == {"deleted": 1}
    assert sysmon.get_learned_profile("stub-sdxl") is None

    async with session_scope() as s:
        await mps.record(
            s,
            model_id="a",
            family="sdxl",
            quant=None,
            ram_gb=1.0,
            vram_gb=2.0,
        )
        await mps.record(
            s,
            model_id="b",
            family="flux",
            quant="nunchaku-fp4",
            ram_gb=3.0,
            vram_gb=4.0,
        )
    sysmon.set_learned_profile("a", ram_gb=1.0, vram_gb=2.0)
    sysmon.set_learned_profile("b", ram_gb=3.0, vram_gb=4.0)

    cleared = await app_client.delete("/api/models/profiles/ignored?all=true")
    assert cleared.status_code == 200
    assert cleared.json() == {"deleted": 2}
    assert sysmon.learned_count() == 0
