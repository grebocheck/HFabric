from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from runtime_env import DotenvError, effective_dotenv, parse_dotenv  # noqa: E402

from app.util.network_policy import is_loopback_host, require_secure_bind  # noqa: E402


def test_dotenv_parser_handles_quotes_comments_and_process_precedence(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "\ufeff# comment\n"
        "HFAB_HOST = 0.0.0.0  # LAN\n"
        "export HFAB_API_TOKEN='literal # token'\n"
        'HFAB_LABEL="line\\nname"\n'
        'HFAB_MODELS="C:\\Models\\weights"\n'
        "HFAB_URL=https://example.test/#fragment\n",
        encoding="utf-8",
    )

    assert parse_dotenv(path) == {
        "HFAB_HOST": "0.0.0.0",
        "HFAB_API_TOKEN": "literal # token",
        "HFAB_LABEL": "line\nname",
        "HFAB_MODELS": r"C:\Models\weights",
        "HFAB_URL": "https://example.test/#fragment",
    }
    assert effective_dotenv(path, {"HFAB_HOST": "127.0.0.1"})["HFAB_HOST"] == "127.0.0.1"


@pytest.mark.parametrize(
    "content",
    ["NOT AN ASSIGNMENT\n", "1INVALID=value\n", "VALUE='unterminated\n", 'VALUE="x" trailing\n'],
)
def test_dotenv_parser_rejects_ambiguous_or_malformed_lines(tmp_path, content):
    path = tmp_path / ".env"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(DotenvError):
        parse_dotenv(path)


def test_network_policy_is_shared_by_launcher_and_backend():
    assert is_loopback_host("127.42.0.1")
    assert is_loopback_host("[::1]")
    assert not is_loopback_host("0.0.0.0")
    with pytest.raises(ValueError, match="Refusing non-loopback"):
        require_secure_bind("0.0.0.0", None, False)
    assert require_secure_bind("0.0.0.0", None, True) is True
    assert require_secure_bind("0.0.0.0", "token", False) is False
