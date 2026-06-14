from __future__ import annotations

import asyncio

from httpx import ASGITransport, AsyncClient
import pytest

from app.main import app


@pytest.fixture
async def client():
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c


async def _wait_done(client: AsyncClient, job_id: str) -> dict:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + 30
    last: dict = {}
    while loop.time() < deadline:
        last = (await client.get(f"/api/jobs/{job_id}")).json()
        if last["status"] in ("done", "error", "cancelled"):
            break
        await asyncio.sleep(0.1)
    assert last["status"] == "done", last
    return last


async def test_upscale_job_runs_through_queue_and_gallery(client: AsyncClient):
    models = (await client.get("/api/models")).json()
    image_model = next(m for m in models if m["job_type"] == "image")
    upscaler = next(m for m in models if m["job_type"] == "upscale")

    created = (await client.post("/api/jobs", json=[{
        "type": "image",
        "model_id": image_model["id"],
        "params": {"prompt": "seed image", "steps": 1, "width": 64, "height": 64},
    }])).json()
    image_job = await _wait_done(client, created[0]["id"])
    source_id = image_job["result"]["image_ids"][0]

    created = (await client.post("/api/jobs", json=[{
        "type": "upscale",
        "model_id": upscaler["id"],
        "params": {"image_id": source_id, "scale": 2},
    }])).json()
    upscale_job = await _wait_done(client, created[0]["id"])
    upscale_id = upscale_job["result"]["image_ids"][0]

    rows = (await client.get("/api/images", params={"family": "upscaler"})).json()
    upscaled = next(row for row in rows if row["id"] == upscale_id)
    assert upscaled["family"] == "upscaler"
    assert upscaled["width"] == 128
    assert upscaled["height"] == 128
    assert upscaled["params"]["upscale"]["scale"] == 2
