from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import audit_gpu_lock  # noqa: E402


def test_gpu_audit_allowlist_accepts_only_documented_findings():
    report = {
        "dependencies": [
            {
                "name": "transformers",
                "vulns": [
                    {"id": "PYSEC-2025-217"},
                    {"id": "PYSEC-2026-2288"},
                    {"id": "PYSEC-2026-2289"},
                    {"id": "PYSEC-2026-2290"},
                ],
            },
            {
                "name": "setuptools",
                "vulns": [{"id": "PYSEC-2026-3447"}],
            },
        ],
        "fixes": [],
    }
    assert audit_gpu_lock.evaluate(report, today=date(2026, 7, 23)) == []


def test_gpu_audit_allowlist_expires(monkeypatch, tmp_path):
    allowlist = tmp_path / "allowlist.json"
    allowlist.write_text(
        '{"schema":1,"entries":[{"id":"VULN-1","package":"pkg",'
        '"expires":"2026-01-01","reason":"temporary compatibility block"}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(audit_gpu_lock, "ALLOWLIST", allowlist)
    with pytest.raises(ValueError, match="expired audit exception"):
        audit_gpu_lock.evaluate(
            {"dependencies": [{"name": "pkg", "vulns": [{"id": "VULN-1"}]}]},
            today=date(2026, 7, 23),
        )
