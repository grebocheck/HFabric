from __future__ import annotations

import json
from pathlib import Path
import zipfile

from fastapi import HTTPException
import pytest

from app.services import chat_attachments as ca
from app.util import uploads


def _upload(token: str, *, filename: str, kind: str, content: bytes, content_type: str = "text/plain") -> dict:
    suffix = Path(filename).suffix or ".bin"
    path = uploads.chat_uploads_dir() / f"{token}{suffix}"
    path.write_bytes(content)
    meta = {
        "token": token,
        "filename": filename,
        "content_type": content_type,
        "kind": kind,
        "size_bytes": len(content),
        "stored_suffix": suffix,
    }
    (uploads.chat_uploads_dir() / f"{token}.json").write_text(json.dumps(meta), encoding="utf-8")
    return uploads.chat_attachment_out(meta)


def test_load_attachment_metadata_dedupes_and_rejects_bad_tokens(isolated_runtime):
    doc = _upload("a" * 32, filename="notes.txt", kind="document", content=b"alpha")
    file_meta = _upload("b" * 32, filename="archive.bin", kind="file", content=b"bits")

    loaded = ca.load_attachment_metadata([doc["token"], doc["token"]])
    assert [item["token"] for item in loaded] == [doc["token"]]
    assert loaded[0]["filename"] == "notes.txt"

    with pytest.raises(HTTPException) as missing:
        ca.load_attachment_metadata(["not-a-token"])
    assert missing.value.status_code == 404

    with pytest.raises(HTTPException) as unsupported:
        ca.load_attachment_metadata([file_meta["token"]])
    assert unsupported.value.status_code == 415


def test_attachment_token_estimate_caps_documents_and_prices_images():
    assert ca.estimate_attachment_tokens([
        {"kind": "image", "size_bytes": 1},
        {"kind": "document", "size_bytes": 10},
        {"kind": "document", "size_bytes": 100_000},
    ]) == ca.IMAGE_TOKEN_COST + 2 + 8192


async def test_build_user_content_injects_document_context(isolated_runtime):
    doc = _upload(
        "c" * 32,
        filename="release.md",
        kind="document",
        content=b"Alpha launch notes\n\nBeta rollback steps",
    )

    content, enriched = await ca.build_user_content(
        "summarize beta",
        [doc],
        allow_images=False,
        max_context_tokens=200,
    )

    assert isinstance(content, str)
    assert "Attached document context follows" in content
    assert "Beta rollback steps" in content
    assert enriched[0]["included_chars"] > 0
    assert enriched[0]["truncated"] is False


async def test_build_user_content_rejects_images_without_mmproj(isolated_runtime):
    image = _upload(
        "d" * 32,
        filename="tiny.png",
        kind="image",
        content=b"png-bytes",
        content_type="image/png",
    )

    with pytest.raises(HTTPException) as exc:
        await ca.build_user_content("describe", [image], allow_images=False, max_context_tokens=50)
    assert exc.value.status_code == 400


async def test_build_user_content_emits_openai_image_parts(isolated_runtime):
    image = _upload(
        "e" * 32,
        filename="tiny.png",
        kind="image",
        content=b"png-bytes",
        content_type="image/png",
    )

    content, enriched = await ca.build_user_content("describe", [image], allow_images=True, max_context_tokens=50)

    assert enriched == [image]
    assert content[0] == {"type": "text", "text": "describe"}
    assert content[1]["type"] == "image_url"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_history_message_content_rehydrates_existing_images(isolated_runtime):
    image = _upload(
        "f" * 32,
        filename="tiny.png",
        kind="image",
        content=b"png-bytes",
        content_type="image/png",
    )
    message = type("Message", (), {"content": "look", "attachments": [image]})()

    parts = ca.history_message_content(message)

    assert parts[0] == {"type": "text", "text": "look"}
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_extract_document_text_handles_text_docx_and_unsupported(isolated_runtime):
    txt = _upload("1" * 32, filename="plain.txt", kind="document", content=b"hello text")
    assert ca.extract_document_text(txt["token"]) == ("hello text", None)

    docx_token = "2" * 32
    docx_path = uploads.chat_uploads_dir() / f"{docx_token}.docx"
    with zipfile.ZipFile(docx_path, "w") as zf:
        zf.writestr(
            "word/document.xml",
            """
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
              <w:body><w:p><w:r><w:t>Hello</w:t></w:r><w:r><w:t> docx</w:t></w:r></w:p></w:body>
            </w:document>
            """,
        )
    (uploads.chat_uploads_dir() / f"{docx_token}.json").write_text(
        json.dumps({
            "token": docx_token,
            "filename": "doc.docx",
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "kind": "document",
            "size_bytes": docx_path.stat().st_size,
            "stored_suffix": ".docx",
        }),
        encoding="utf-8",
    )
    assert ca.extract_document_text(docx_token) == ("Hello docx", None)

    blob = _upload(
        "3" * 32,
        filename="blob.bin",
        kind="document",
        content=b"bits",
        content_type="application/octet-stream",
    )
    assert ca.extract_document_text(blob["token"]) == ("", "unsupported document format")
    assert ca.extract_document_text("missing") == ("", "attachment file is missing")


async def test_document_context_marks_budget_and_extraction_notices(isolated_runtime):
    first = _upload("4" * 32, filename="first.txt", kind="document", content=b"alpha " * 60)
    second = _upload("5" * 32, filename="second.txt", kind="document", content=b"beta")

    context, enriched = await ca.build_document_context("alpha", [first, second], max_context_chars=260)

    assert "Attachment 1" in context
    assert enriched[0]["included_chars"] > 0
    assert enriched[1]["notice"] == "not injected: token budget already used"
    assert enriched[1]["truncated"] is True
