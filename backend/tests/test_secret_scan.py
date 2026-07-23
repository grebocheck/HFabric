from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from check_secrets import findings  # noqa: E402


def test_secret_scan_detects_high_confidence_tokens_without_echoing_values():
    token = "ghp_" + "a" * 40
    assert findings(f"TOKEN={token}\n") == [(1, "GitHub token")]


def test_secret_scan_supports_explicit_fixture_allowlist():
    token = "hf_" + "a" * 40
    assert findings(f"TOKEN={token}  # pragma: allowlist secret\n") == []
