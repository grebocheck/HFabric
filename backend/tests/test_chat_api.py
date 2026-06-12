from __future__ import annotations


async def _model_ids(client) -> tuple[str, str]:
    models = (await client.get("/api/models")).json()
    llm_id = next(m["id"] for m in models if m["job_type"] == "llm")
    image_id = next(m["id"] for m in models if m["job_type"] == "image")
    return llm_id, image_id


async def test_conversation_crud(app_client):
    llm_id, _ = await _model_ids(app_client)

    created = (await app_client.post(
        "/api/chat/conversations",
        json={"title": "Spec chat", "model_id": llm_id, "system": "Be brief"},
    )).json()

    listed = (await app_client.get("/api/chat/conversations")).json()
    assert [row["id"] for row in listed] == [created["id"]]

    detail = (await app_client.get(f"/api/chat/conversations/{created['id']}")).json()
    assert detail["title"] == "Spec chat"
    assert detail["model_id"] == llm_id
    assert detail["messages"] == []

    updated = (await app_client.patch(
        f"/api/chat/conversations/{created['id']}",
        json={"title": "Renamed", "params": {"temperature": 0.2}},
    )).json()
    assert updated["title"] == "Renamed"
    assert updated["params"]["temperature"] == 0.2

    missing = await app_client.get("/api/chat/conversations/not-real")
    assert missing.status_code == 404

    deleted = (await app_client.delete(f"/api/chat/conversations/{created['id']}")).json()
    assert deleted == {"deleted": True}
    assert (await app_client.get(f"/api/chat/conversations/{created['id']}")).status_code == 404


async def test_message_send_worker_reply_and_regenerate_edit_paths(app_client, wait_jobs_done):
    llm_id, _ = await _model_ids(app_client)
    conv = (await app_client.post("/api/chat/conversations", json={"model_id": llm_id})).json()

    first = (await app_client.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={"content": "a tiny castle", "model_id": llm_id, "max_tokens": 64},
    )).json()
    queued = (await app_client.get(f"/api/jobs/{first['job_id']}")).json()
    assert queued["status"] in {"queued", "running", "done"}

    jobs = await wait_jobs_done(app_client, [first["job_id"]])
    assert jobs[0]["status"] == "done"

    detail = (await app_client.get(f"/api/chat/conversations/{conv['id']}")).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["content"] == "a tiny castle"
    assert "masterpiece" in detail["messages"][1]["content"]
    assert "a tiny castle" in detail["messages"][1]["content"]

    # Regenerate: remove the last user turn and assistant reply, then resend it.
    removed = (await app_client.delete(
        f"/api/chat/conversations/{conv['id']}/messages/{detail['messages'][0]['id']}"
    )).json()
    assert removed["removed"] == 2
    regen = (await app_client.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={"content": "a tiny castle", "model_id": llm_id, "max_tokens": 64},
    )).json()
    await wait_jobs_done(app_client, [regen["job_id"]])
    regenerated = (await app_client.get(f"/api/chat/conversations/{conv['id']}")).json()
    assert [m["role"] for m in regenerated["messages"]] == ["user", "assistant"]

    # Edit: truncate from the user message again and send the changed content.
    edit_removed = (await app_client.delete(
        f"/api/chat/conversations/{conv['id']}/messages/{regenerated['messages'][0]['id']}"
    )).json()
    assert edit_removed["removed"] == 2
    edited = (await app_client.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={"content": "an edited tiny castle", "model_id": llm_id, "max_tokens": 64},
    )).json()
    await wait_jobs_done(app_client, [edited["job_id"]])
    final = (await app_client.get(f"/api/chat/conversations/{conv['id']}")).json()
    assert [m["content"] for m in final["messages"] if m["role"] == "user"] == ["an edited tiny castle"]
    assert "an edited tiny castle" in final["messages"][1]["content"]


async def test_image_bridge_persists_generated_image_markdown(app_client, wait_jobs_done):
    _, image_id = await _model_ids(app_client)
    conv = (await app_client.post("/api/chat/conversations", json={})).json()

    sent = (await app_client.post(
        f"/api/chat/conversations/{conv['id']}/image",
        json={
            "prompt": "blue square",
            "model_id": image_id,
            "steps": 1,
            "width": 256,
            "height": 256,
        },
    )).json()

    jobs = await wait_jobs_done(app_client, [sent["job_id"]])
    assert jobs[0]["status"] == "done"
    assert jobs[0]["result"]["image_ids"]

    detail = (await app_client.get(f"/api/chat/conversations/{conv['id']}")).json()
    assert detail["messages"][0]["content"] == "/image blue square"
    assistant = detail["messages"][1]
    assert assistant["job_id"] is None
    assert assistant["content"].startswith("![blue square](/api/images/")


async def test_chat_send_validation_errors(app_client):
    llm_id, image_id = await _model_ids(app_client)
    conv = (await app_client.post("/api/chat/conversations", json={})).json()

    empty = await app_client.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={"content": "   ", "model_id": llm_id},
    )
    assert empty.status_code == 400
    assert "message content is empty" in empty.text

    missing_image_model = await app_client.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={"content": "make an image", "model_id": llm_id, "image_tool": True},
    )
    assert missing_image_model.status_code == 400

    wrong_type = await app_client.post(
        f"/api/chat/conversations/{conv['id']}/messages",
        json={"content": "hello", "model_id": image_id},
    )
    assert wrong_type.status_code == 400

    missing_conv = await app_client.post(
        "/api/chat/conversations/not-real/messages",
        json={"content": "hello", "model_id": llm_id},
    )
    assert missing_conv.status_code == 404
