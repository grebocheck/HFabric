from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def test_launchers_never_use_unscoped_process_kills():
    powershell = (ROOT / "scripts" / "run.ps1").read_text(encoding="utf-8")
    shell = (ROOT / "run.sh").read_text(encoding="utf-8")

    assert "Stop-Port" not in powershell
    assert "Get-Process -Name" not in powershell
    assert "Get-Job | Remove-Job" not in powershell
    assert not re.search(r"\bfuser\s+-k\b", shell)
    assert not re.search(r"\bpkill\b", shell)
    assert not re.search(r"\bkill\s+-9\s+\$", shell)


def test_launchers_fail_closed_on_occupied_ports_and_insecure_lan():
    powershell = (ROOT / "scripts" / "run.ps1").read_text(encoding="utf-8")
    shell = (ROOT / "run.sh").read_text(encoding="utf-8")
    policy = (ROOT / "backend" / "app" / "util" / "network_policy.py").read_text(
        encoding="utf-8"
    )

    assert "Assert-PortAvailable" in powershell
    assert "runtime_env.py" in powershell
    assert "--check-security" in powershell
    assert "assert_port_available" in shell
    assert "runtime_env.py" in shell
    assert "--check-security" in shell
    assert "HFAB_ALLOW_INSECURE_LAN" in policy
