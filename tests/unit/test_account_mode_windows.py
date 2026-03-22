"""Tests for Windows-safe subprocess execution in CLI account mode providers."""
from __future__ import annotations

import asyncio
import importlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def _fake_win32(monkeypatch):
    """Simulate Windows platform."""
    monkeypatch.setattr(sys, "platform", "win32")


@pytest.fixture
def _fake_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")


@pytest.fixture(autouse=True)
def _fresh_cli_account():
    """Forzar reimportación de cli_account para cada test, evitando state stale."""
    mod_key = "tools.gimo_server.providers.cli_account"
    if mod_key in sys.modules:
        importlib.reload(sys.modules[mod_key])
    yield
    if mod_key in sys.modules:
        importlib.reload(sys.modules[mod_key])


def _mock_proc(stdout: bytes = b'{"result":"ok"}', stderr: bytes = b"", rc: int = 0):
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(stdout, stderr))
    proc.returncode = rc
    return proc


# ---------------------------------------------------------------------------
# cli_account.py — CliAccountAdapter
# ---------------------------------------------------------------------------

class TestCliAccountAdapterWindows:
    @pytest.mark.asyncio
    async def test_generate_uses_shell_on_windows(self, _fake_win32, monkeypatch):
        """En Windows, generate() usa create_subprocess_shell."""
        from tools.gimo_server.providers import cli_account as mod

        monkeypatch.setattr("shutil.which", lambda _: "/fake/codex")

        captured = {}

        async def fake_shell(cmd_str, **kwargs):
            captured["cmd"] = cmd_str
            return _mock_proc()

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)

        adapter = mod.CliAccountAdapter(binary="codex")
        await adapter.generate("hello", {})

        assert "codex" in captured["cmd"]
        assert "exec" in captured["cmd"]

    @pytest.mark.asyncio
    async def test_generate_uses_exec_on_linux(self, _fake_linux, monkeypatch):
        """En Linux, generate() usa create_subprocess_exec."""
        from tools.gimo_server.providers import cli_account as mod

        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/codex")

        captured = {}

        async def fake_exec(*args, **kwargs):
            captured["args"] = args
            return _mock_proc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        adapter = mod.CliAccountAdapter(binary="codex")
        await adapter.generate("hello", {})

        assert captured["args"][0] == "codex"

    @pytest.mark.asyncio
    async def test_health_check_uses_shell_on_windows(self, _fake_win32, monkeypatch):
        """En Windows, health_check() usa create_subprocess_shell."""
        from tools.gimo_server.providers import cli_account as mod

        monkeypatch.setattr("shutil.which", lambda _: "/fake/codex")

        captured = {}

        async def fake_shell(cmd_str, **kwargs):
            captured["cmd"] = cmd_str
            return _mock_proc(stdout=b"0.113.0")

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)

        adapter = mod.CliAccountAdapter(binary="codex")
        result = await adapter.health_check()

        assert result is True
        assert "codex" in captured["cmd"]
        assert "--version" in captured["cmd"]


# ---------------------------------------------------------------------------
# codex_auth_service.py — start_device_flow
# ---------------------------------------------------------------------------

class TestCodexAuthServiceWindows:
    @pytest.mark.asyncio
    async def test_device_flow_returns_error_when_cli_missing(self, monkeypatch):
        monkeypatch.setattr("tools.gimo_server.services.codex_auth_service.shutil.which", lambda _: None)
        from tools.gimo_server.services.codex_auth_service import CodexAuthService
        result = await CodexAuthService.start_device_flow()
        assert result["status"] == "error"
        assert "Codex CLI no detectado" in result["message"]


# ---------------------------------------------------------------------------
# provider_connector_service.py — _resolve_cli_version
# ---------------------------------------------------------------------------

class TestConnectorResolveVersionWindows:
    @pytest.mark.asyncio
    async def test_resolve_cli_version_uses_shell_on_windows(self, _fake_win32, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: "/fake/codex")

        captured = {}

        async def fake_shell(cmd_str, **kwargs):
            captured["cmd"] = cmd_str
            return _mock_proc(stdout=b"codex-cli 0.113.0")

        monkeypatch.setattr(asyncio, "create_subprocess_shell", fake_shell)

        from tools.gimo_server.services.provider_connector_service import ProviderConnectorService
        version = await ProviderConnectorService._resolve_cli_version("codex")

        assert version is not None
        assert "codex" in captured["cmd"]
