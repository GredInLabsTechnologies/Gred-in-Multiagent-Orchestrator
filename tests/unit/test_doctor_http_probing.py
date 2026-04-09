"""R19 Change 5 — doctor exposes an HTTP probing hint without leaking the token.

The /ops/* boundary stays fail-closed (no anonymous routes). The doctor command
must:
  1. Tell the operator whether an operator token is resolvable from the
     existing bootstrap chain (bond / env / config).
  2. NEVER print the literal token value on stdout.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from gimo_cli.commands import auth as auth_cmd


SECRET = "SECRET_TOKEN_MUST_NOT_LEAK_abc123"


def _run_doctor(capsys, *, token: str | None) -> str:
    """Invoke doctor() with all external deps mocked, return captured stdout."""
    with patch.object(auth_cmd, "resolve_token", return_value=token), \
         patch.object(auth_cmd, "load_cli_bond", return_value=None), \
         patch.object(auth_cmd, "load_bond", return_value=None), \
         patch.object(auth_cmd, "load_config", return_value={}), \
         patch.object(auth_cmd, "resolve_server_url", return_value="http://127.0.0.1:9325"), \
         patch.object(auth_cmd, "verify_bond_jwt", return_value=None), \
         patch("gimo_cli.commands.auth.httpx.Client") as mock_client:
        mock_client.return_value.__enter__.return_value.get.side_effect = Exception("unreachable")
        auth_cmd.doctor()
    return capsys.readouterr().out


def test_doctor_http_probing_section_present_with_token(capsys):
    out = _run_doctor(capsys, token=SECRET)
    assert "HTTP probing" in out
    assert "Operator token" in out
    # Critical: the literal secret must never appear on stdout.
    assert SECRET not in out
    # Hint should mention the env var name, not the token.
    assert "ORCH_OPERATOR_TOKEN" in out
    # Boundary statement must remain.
    assert "fail-closed" in out


def test_doctor_http_probing_warns_when_token_missing(capsys):
    out = _run_doctor(capsys, token=None)
    assert "HTTP probing" in out
    assert "not resolvable" in out
    # No token = nothing to leak, but the warning path must still surface.
    assert "gimo login" in out
