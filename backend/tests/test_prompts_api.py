from __future__ import annotations


async def test_prompt_library_crud_search_and_validation(app_client):
    # empty body is rejected
    assert (await app_client.post("/api/prompts", json={"body": "   "})).status_code == 422

    # name falls back to the first line of the body; tags are trimmed + de-duped
    created = (await app_client.post(
        "/api/prompts",
        json={
            "body": "neon city at night\nrain, reflections",
            "negative": " blurry ",
            "tags": ["Cyberpunk", "cyberpunk", " night "],
        },
    )).json()
    assert created["name"] == "neon city at night"
    assert created["negative"] == "blurry"
    assert created["tags"] == ["Cyberpunk", "night"]

    explicit = (await app_client.post(
        "/api/prompts",
        json={"name": "Portrait base", "body": "studio portrait, soft light", "tags": ["people"]},
    )).json()
    assert explicit["name"] == "Portrait base"

    # free-text search matches name or body
    by_body = (await app_client.get("/api/prompts?q=neon")).json()
    assert [p["id"] for p in by_body] == [created["id"]]

    # tag filter is case-insensitive and exact-per-tag
    by_tag = (await app_client.get("/api/prompts?tag=people")).json()
    assert [p["id"] for p in by_tag] == [explicit["id"]]

    listed = (await app_client.get("/api/prompts")).json()
    assert {p["id"] for p in listed} == {created["id"], explicit["id"]}


async def test_prompt_update_and_delete(app_client):
    created = (await app_client.post("/api/prompts", json={"body": "a cat"})).json()

    updated = (await app_client.patch(
        f"/api/prompts/{created['id']}",
        json={"name": "Cat", "tags": ["animal"], "negative": "ugly"},
    )).json()
    assert updated["name"] == "Cat"
    assert updated["tags"] == ["animal"]
    assert updated["negative"] == "ugly"
    assert updated["updated_at"] >= created["updated_at"]

    assert (await app_client.patch("/api/prompts/missing", json={"name": "x"})).status_code == 404

    deleted = (await app_client.delete(f"/api/prompts/{created['id']}")).json()
    assert deleted == {"deleted": created["id"]}
    assert (await app_client.delete(f"/api/prompts/{created['id']}")).status_code == 404


async def test_prompt_import_skips_empty_and_returns_items(app_client):
    result = (await app_client.post(
        "/api/prompts/import",
        json={"prompts": [
            {"name": "One", "body": "first prompt", "tags": ["x"]},
            {"body": "   "},  # skipped — no body
            {"body": "second prompt"},
        ]},
    )).json()

    assert result["imported"] == 2
    names = {p["name"] for p in result["prompts"]}
    assert names == {"One", "second prompt"}
