from __future__ import annotations

import pytest

from app.api import code
from app.config import settings


async def test_code_workspace_excludes_secrets_but_keeps_env_template(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "root", tmp_path)
    (tmp_path / "safe.py").write_text("print('safe')\n", encoding="utf-8")
    (tmp_path / ".env").write_text("HFAB_API_TOKEN=secret\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("TOKEN=secret\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("HFAB_API_TOKEN=change-me\n", encoding="utf-8")
    (tmp_path / "credentials.json").write_text('{"token":"secret"}\n', encoding="utf-8")
    (tmp_path / "private.pem").write_text("secret\n", encoding="utf-8")
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_ed25519").write_text("secret\n", encoding="utf-8")
    (tmp_path / "service-account.json").write_text('{"private_key":"secret"}\n', encoding="utf-8")

    files = await code.list_code_files(q=None, limit=120)
    paths = {item["path"] for item in files}

    assert paths == {".env.example", "safe.py"}
    with pytest.raises(code.HTTPException, match="sensitive file"):
        await code.get_code_file(path=".env")
    with pytest.raises(code.HTTPException, match="sensitive file"):
        await code.get_code_file(path="credentials.json")


async def test_code_file_read_is_bounded_and_rejects_escape(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "root", tmp_path)
    payload = "x" * (code.MAX_FILE_BYTES + 10)
    (tmp_path / "large.txt").write_text(payload, encoding="utf-8")

    result = await code.get_code_file(path="large.txt")
    assert result["truncated"] is True
    assert len(result["content"]) == code.MAX_FILE_BYTES

    with pytest.raises(code.HTTPException, match="escapes repository root"):
        await code.get_code_file(path="../outside.txt")
