from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.services import llama_manager


def _exe(system: str) -> str:
    return ".exe" if system.lower().startswith("win") else ""


def _fake_extracted(tmp: Path, name: str, system: str) -> Path:
    src = tmp / name
    (src / "build" / "bin").mkdir(parents=True)
    (src / "build" / "bin" / f"llama-server{_exe(system)}").write_text("bin")
    (src / "build" / "bin" / f"llama-tts{_exe(system)}").write_text("bin")
    return src


def _pin_llama_settings(monkeypatch):
    # Make the manager's setattr on these paths auto-revert after the test.
    for attr in ("llama_server_bin", "llama_tts_bin", "llama_mtmd_bin"):
        monkeypatch.setattr(settings, attr, getattr(settings, attr))


def test_state_is_empty_for_fresh_root(monkeypatch, tmp_path):
    monkeypatch.setattr(llama_manager, "MANAGED_ROOT", tmp_path / "llama")
    s = llama_manager.state()
    assert s["active"] is None
    assert s["versions"] == []
    assert s["keep_versions"] == 3
    assert "variant" in s


def test_install_blocking_registers_and_repoints_settings(monkeypatch, tmp_path):
    root = tmp_path / "llama"
    monkeypatch.setattr(llama_manager, "MANAGED_ROOT", root)
    _pin_llama_settings(monkeypatch)
    lr = llama_manager._llama_release()

    def fake_install(target, *, system, machine, variant, tag=None, progress_cb=None):
        if progress_cb:
            progress_cb("fake-asset.zip", 50, 100)
        src = _fake_extracted(tmp_path, "extracted", system)
        version = lr.register_version(
            target, tag=tag or "b100", variant=variant, extracted_dir=src, system=system,
        )
        version["variant_matched"] = True
        return version

    monkeypatch.setattr(lr, "install", fake_install)

    version = llama_manager.install_blocking(tag="b100", variant="cpu")
    assert version["tag"] == "b100"

    status = llama_manager.get_status()
    assert status["state"] == "done"
    # settings now point at the freshly installed binary.
    assert Path(settings.llama_server_bin).exists()
    assert version["id"] in str(settings.llama_server_bin)


def test_install_blocking_records_error(monkeypatch, tmp_path):
    monkeypatch.setattr(llama_manager, "MANAGED_ROOT", tmp_path / "llama")
    lr = llama_manager._llama_release()

    def boom(*a, **k):
        raise ValueError("no asset for this platform")

    monkeypatch.setattr(lr, "install", boom)
    try:
        llama_manager.install_blocking(variant="cpu")
    except ValueError:
        pass
    status = llama_manager.get_status()
    assert status["state"] == "error"
    assert "no asset" in status["message"]


def test_activate_and_remove_through_manager(monkeypatch, tmp_path):
    root = tmp_path / "llama"
    monkeypatch.setattr(llama_manager, "MANAGED_ROOT", root)
    _pin_llama_settings(monkeypatch)
    lr = llama_manager._llama_release()

    lr.register_version(root, tag="b1", variant="cpu", extracted_dir=_fake_extracted(tmp_path, "e1", "Linux"), system="Linux")
    v2 = lr.register_version(root, tag="b2", variant="cpu", extracted_dir=_fake_extracted(tmp_path, "e2", "Linux"), system="Linux")

    # b2 is active; roll back to b1, then drop b2.
    llama_manager.activate("b1-cpu")
    assert lr.read_state(root)["active"] == "b1-cpu"
    llama_manager.remove(v2["id"])
    assert all(v["id"] != v2["id"] for v in lr.read_state(root)["versions"])


def test_check_update_compares_tags(monkeypatch, tmp_path):
    root = tmp_path / "llama"
    monkeypatch.setattr(llama_manager, "MANAGED_ROOT", root)
    lr = llama_manager._llama_release()
    lr.register_version(root, tag="b1", variant="cpu", extracted_dir=_fake_extracted(tmp_path, "e1", "Linux"), system="Linux")

    monkeypatch.setattr(lr, "fetch_latest_release", lambda: {
        "tag_name": "b2",
        "assets": [{"name": "llama-b2-bin-ubuntu-x64.zip", "browser_download_url": "https://x/z.zip"}],
    })
    monkeypatch.setattr(llama_manager.platform, "system", lambda: "Linux")
    monkeypatch.setattr(llama_manager.platform, "machine", lambda: "x86_64")

    result = llama_manager.check_update(variant="cpu")
    assert result["latest_tag"] == "b2"
    assert result["active_tag"] == "b1"
    assert result["update_available"] is True


async def test_api_state_and_activate(monkeypatch, tmp_path, app_client):
    root = tmp_path / "llama"
    monkeypatch.setattr(llama_manager, "MANAGED_ROOT", root)
    _pin_llama_settings(monkeypatch)
    lr = llama_manager._llama_release()
    lr.register_version(root, tag="b1", variant="cpu", extracted_dir=_fake_extracted(tmp_path, "e1", "Linux"), system="Linux")
    lr.register_version(root, tag="b2", variant="cpu", extracted_dir=_fake_extracted(tmp_path, "e2", "Linux"), system="Linux")

    body = (await app_client.get("/api/llama")).json()
    assert {v["tag"] for v in body["versions"]} == {"b1", "b2"}
    assert body["active"] == "b2-cpu"

    activated = (await app_client.post("/api/llama/activate", json={"id": "b1-cpu"})).json()
    assert activated["active"] == "b1-cpu"

    # Removing the active build is refused.
    refused = await app_client.delete("/api/llama/b1-cpu")
    assert refused.status_code == 409

    removed = await app_client.delete("/api/llama/b2-cpu")
    assert removed.status_code == 200
    assert {v["tag"] for v in removed.json()["versions"]} == {"b1"}
