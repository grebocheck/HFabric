from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import llama_release as lr  # noqa: E402


def assets(*names: str) -> list[dict]:
    return [{"name": n, "browser_download_url": f"https://x/{n}", "size": 1} for n in names]


# ------------------------------------------------------------ asset selection

def test_windows_cuda_picks_cuda_zip_and_cudart_extra():
    result = lr.select_assets(
        assets(
            "llama-b6543-bin-win-cpu-x64.zip",
            "llama-b6543-bin-win-cuda-12.4-x64.zip",
            "cudart-llama-bin-win-cuda-12.4-x64.zip",
            "llama-b6543-bin-ubuntu-x64.zip",
        ),
        system="Windows", machine="AMD64", variant="cuda",
    )
    assert result["primary"]["name"] == "llama-b6543-bin-win-cuda-12.4-x64.zip"
    assert result["variant_matched"] is True
    assert [a["name"] for a in result["extras"]] == ["cudart-llama-bin-win-cuda-12.4-x64.zip"]


def test_linux_cpu_picks_ubuntu_zip():
    result = lr.select_assets(
        assets("llama-b6543-bin-win-cpu-x64.zip", "llama-b6543-bin-ubuntu-x64.zip"),
        system="Linux", machine="x86_64", variant="cpu",
    )
    assert result["primary"]["name"] == "llama-b6543-bin-ubuntu-x64.zip"


def test_macos_arm64_picks_macos_arm_build():
    result = lr.select_assets(
        assets("llama-b6543-bin-macos-arm64.zip", "llama-b6543-bin-macos-x64.zip"),
        system="Darwin", machine="arm64", variant="cpu",
    )
    assert result["primary"]["name"] == "llama-b6543-bin-macos-arm64.zip"


def test_falls_back_to_cpu_when_no_accelerator_build():
    result = lr.select_assets(
        assets("llama-b6543-bin-win-cpu-x64.zip"),
        system="Windows", machine="AMD64", variant="cuda",
    )
    assert result["primary"]["name"] == "llama-b6543-bin-win-cpu-x64.zip"
    assert result["variant_matched"] is False
    assert result["extras"] == []


def test_no_matching_platform_asset_returns_none():
    result = lr.select_assets(
        assets("llama-b6543-bin-macos-arm64.zip"),
        system="Linux", machine="x86_64", variant="cpu",
    )
    assert result["primary"] is None
    assert "no Linux" in result["reason"]


def test_backend_to_variant_mapping():
    assert lr.backend_to_variant("cuda", "Windows") == "cuda"
    assert lr.backend_to_variant("rocm", "Windows") == "hip"
    assert lr.backend_to_variant("rocm", "Linux") == "vulkan"
    assert lr.backend_to_variant("cpu", "Linux") == "cpu"
    assert lr.backend_to_variant(None, "Linux") == "cpu"


# ------------------------------------------------------ versioning / state

def _fake_build(tmp: Path, name: str) -> Path:
    src = tmp / name
    (src / "build" / "bin").mkdir(parents=True)
    (src / "build" / "bin" / "llama-server").write_text("#!/bin/sh\n")
    (src / "build" / "bin" / "llama-tts").write_text("#!/bin/sh\n")
    return src


def test_register_finds_binaries_activates_and_prunes(tmp_path):
    root = tmp_path / "llama"
    v1 = lr.register_version(
        root, tag="b1", variant="cpu", extracted_dir=_fake_build(tmp_path, "e1"), system="Linux",
    )
    assert v1["binaries"]["llama-server"].endswith("llama-server")
    assert "llama-tts" in v1["binaries"]
    state = lr.read_state(root)
    assert state["active"] == v1["id"]
    assert lr.active_version(root)["tag"] == "b1"


def test_register_without_server_raises(tmp_path):
    root = tmp_path / "llama"
    src = tmp_path / "empty"
    (src / "bin").mkdir(parents=True)
    (src / "bin" / "notes.txt").write_text("no binary here")
    try:
        lr.register_version(root, tag="bX", variant="cpu", extracted_dir=src, system="Linux")
    except ValueError as exc:
        assert "no llama-server" in str(exc)
    else:
        raise AssertionError("expected missing-server failure")


def test_prune_keeps_three_newest_plus_active(tmp_path):
    root = tmp_path / "llama"
    versions = []
    for i in range(5):
        d = root / "versions" / f"b{i}-cpu"
        d.mkdir(parents=True)
        (d / "llama-server").write_text("x")
        versions.append({
            "id": f"b{i}-cpu", "tag": f"b{i}", "variant": "cpu",
            "installed_at": f"2026-06-1{i}T00:00:00+00:00", "dir": str(d),
            "binaries": {"llama-server": str(d / "llama-server")},
        })
    # Make the OLDEST version active to prove active is never pruned.
    lr.write_state(root, {"schema_version": 1, "active": "b0-cpu", "versions": versions})

    removed = lr.prune(root, keep=3)
    kept = {v["id"] for v in lr.read_state(root)["versions"]}
    assert "b0-cpu" in kept  # active survived despite being oldest
    assert "b4-cpu" in kept and "b3-cpu" in kept  # newest survive
    assert len(kept) == 3
    assert set(removed).isdisjoint(kept)


def test_cannot_remove_active_version(tmp_path):
    root = tmp_path / "llama"
    lr.register_version(root, tag="b1", variant="cpu", extracted_dir=_fake_build(tmp_path, "e1"), system="Linux")
    active = lr.read_state(root)["active"]
    try:
        lr.remove_version(root, active)
    except ValueError as exc:
        assert "active" in str(exc)
    else:
        raise AssertionError("expected active-removal guard")


def test_activate_switches_and_remove_inactive(tmp_path):
    root = tmp_path / "llama"
    lr.register_version(root, tag="b1", variant="cpu", extracted_dir=_fake_build(tmp_path, "e1"), system="Linux")
    v2 = lr.register_version(root, tag="b2", variant="cpu", extracted_dir=_fake_build(tmp_path, "e2"), system="Linux")
    # b2 is active now; switch back to b1, then remove b2.
    lr.activate(root, "b1-cpu")
    assert lr.read_state(root)["active"] == "b1-cpu"
    lr.remove_version(root, v2["id"])
    assert all(v["id"] != v2["id"] for v in lr.read_state(root)["versions"])
