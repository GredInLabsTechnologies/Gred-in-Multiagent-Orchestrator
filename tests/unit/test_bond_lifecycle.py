"""Tests for bond auto-lifecycle (Change 4)."""

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest


class TestBondAutoLifecycle:
    """Test that expired bonds are auto-deleted and login clears stale state."""

    def test_expired_bond_auto_deleted(self, tmp_path, monkeypatch):
        """resolve_bond_token should delete bond.enc when JWT is expired."""
        from gimo_cli.bond import resolve_bond_token, save_cli_bond, _bond_enc_path

        # Point bond storage to tmp
        bond_path = tmp_path / "bond.enc"
        monkeypatch.setattr("gimo_cli.bond._bond_enc_path", lambda: bond_path)

        # Create a bond file with dummy content
        bond_path.write_text("dummy", encoding="utf-8")
        assert bond_path.exists()

        # Mock load_cli_bond to return a bond, verify_bond_jwt to return None (expired)
        monkeypatch.setattr("gimo_cli.bond.load_cli_bond", lambda: {"jwt": "expired-token"})
        monkeypatch.setattr("gimo_cli.bond.verify_bond_jwt", lambda t: None)

        token, hint = resolve_bond_token()

        assert token is None
        assert "expired" in hint.lower() or "invalid" in hint.lower()
        assert not bond_path.exists(), "Expired bond.enc should be auto-deleted"

    def test_valid_bond_not_deleted(self, tmp_path, monkeypatch):
        """resolve_bond_token should NOT delete a valid bond."""
        from gimo_cli.bond import resolve_bond_token

        bond_path = tmp_path / "bond.enc"
        bond_path.write_text("valid", encoding="utf-8")
        monkeypatch.setattr("gimo_cli.bond._bond_enc_path", lambda: bond_path)

        monkeypatch.setattr("gimo_cli.bond.load_cli_bond", lambda: {"jwt": "valid-token"})
        monkeypatch.setattr("gimo_cli.bond.verify_bond_jwt", lambda t: {"sub": "user", "exp": 9999999999})

        token, hint = resolve_bond_token()

        assert token == "valid-token"
        assert hint is None
        assert bond_path.exists(), "Valid bond should NOT be deleted"

    def test_warning_fires_once_then_silent(self, tmp_path, monkeypatch):
        """After auto-delete, second call returns (None, None) — no bond file, no hint."""
        from gimo_cli.bond import resolve_bond_token

        bond_path = tmp_path / "bond.enc"
        bond_path.write_text("dummy", encoding="utf-8")
        monkeypatch.setattr("gimo_cli.bond._bond_enc_path", lambda: bond_path)

        call_count = [0]
        def mock_load():
            call_count[0] += 1
            if call_count[0] == 1:
                return {"jwt": "expired"}
            return None  # Bond file deleted on first call

        monkeypatch.setattr("gimo_cli.bond.load_cli_bond", mock_load)
        monkeypatch.setattr("gimo_cli.bond.verify_bond_jwt", lambda t: None)

        # First call: expired bond, hint returned
        _token1, hint1 = resolve_bond_token()
        assert hint1 is not None

        # Second call: no bond file, silent
        _token2, hint2 = resolve_bond_token()
        assert hint2 is None

    def test_no_bond_returns_none_none(self, tmp_path, monkeypatch):
        """When no bond file exists, return (None, None) — fall through to legacy."""
        from gimo_cli.bond import resolve_bond_token

        monkeypatch.setattr("gimo_cli.bond.load_cli_bond", lambda: None)

        token, hint = resolve_bond_token()
        assert token is None
        assert hint is None
