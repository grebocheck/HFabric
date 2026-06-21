from __future__ import annotations


async def test_notes_crud_and_validation(app_client):
    created = (await app_client.post("/api/notes", json={"title": "  ", "content": "scratch"})).json()
    assert created["title"] == "Untitled note"
    assert created["content"] == "scratch"

    listed = (await app_client.get("/api/notes?q=scratch")).json()
    assert [note["id"] for note in listed] == [created["id"]]

    fetched = (await app_client.get(f"/api/notes/{created['id']}")).json()
    assert fetched["content"] == "scratch"

    updated = (await app_client.patch(
        f"/api/notes/{created['id']}",
        json={"title": "Plan", "content": "updated body"},
    )).json()
    assert updated["title"] == "Plan"
    assert updated["content"] == "updated body"

    assert (await app_client.get("/api/notes?limit=1001")).status_code == 422
    assert (await app_client.patch("/api/notes/not-real", json={"title": "x"})).status_code == 404

    deleted = (await app_client.delete(f"/api/notes/{created['id']}")).json()
    assert deleted == {"deleted": created["id"]}
    assert (await app_client.get(f"/api/notes/{created['id']}")).status_code == 404


async def test_presets_crud_import_conflicts_and_validation(app_client):
    created = (await app_client.post(
        "/api/presets",
        json={"name": "Fast image", "type": "image", "params": {"steps": 4}},
    )).json()
    assert created["name"] == "Fast image"
    assert created["type"] == "image"

    duplicate = await app_client.post(
        "/api/presets",
        json={"name": "Fast image", "type": "image", "params": {}},
    )
    assert duplicate.status_code == 409

    imported = (await app_client.post(
        "/api/presets/import",
        json={"on_conflict": "rename", "presets": [{"name": "Fast image", "type": "llm", "params": {"temperature": 0.4}}]},
    )).json()
    assert imported["imported"] == 1
    assert imported["presets"][0]["name"] == "Fast image (2)"

    skipped = (await app_client.post(
        "/api/presets/import",
        json={"on_conflict": "skip", "presets": [{"name": "Fast image", "type": "image", "params": {}}]},
    )).json()
    assert skipped["imported"] == 0
    assert skipped["skipped"] == 1

    names = [preset["name"] for preset in (await app_client.get("/api/presets")).json()]
    assert names == ["Fast image (2)", "Fast image"]

    bad_type = await app_client.post("/api/presets", json={"name": "Bad", "type": "audio", "params": {}})
    assert bad_type.status_code == 422

    deleted = (await app_client.delete(f"/api/presets/{created['id']}")).json()
    assert deleted == {"deleted": created["id"]}
    assert (await app_client.delete("/api/presets/not-real")).status_code == 404


async def test_code_workspace_lists_reads_and_rejects_bad_paths(app_client):
    files = (await app_client.get("/api/code/files?q=ROADMAP&limit=10")).json()
    assert any(row["path"] == "ROADMAP.md" for row in files)

    roadmap = (await app_client.get("/api/code/file", params={"path": "ROADMAP.md"})).json()
    assert roadmap["path"] == "ROADMAP.md"
    # A stable, load-bearing heading (the shipped-phase markers like P16 now live
    # in docs/history.md, so don't assert on those here).
    assert "Memory invariants" in roadmap["content"]
    assert roadmap["truncated"] is False

    escape = await app_client.get("/api/code/file", params={"path": "../.env"})
    assert escape.status_code == 400
    assert "escapes repository root" in escape.text

    ignored = await app_client.get("/api/code/file", params={"path": ".git/config"})
    assert ignored.status_code == 400
    assert "path is ignored" in ignored.text

    missing = await app_client.get("/api/code/file", params={"path": "does-not-exist.txt"})
    assert missing.status_code == 404
