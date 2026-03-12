"""Tests for Windows-safe subprocess execution in CLI account mode providers."""
from __future__ import annotations

import asyncio
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


# ---------------------------------------------------------------------------
# cli_account.py — CliAccountAdapter
# ---------------------------------------------------------------------------

class TestCliAccountAdapterWindows:
    @pytest.mark.asyncio
    async def test_generate_uses_shell_on_windows(self, _fake_win32, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: "/fake/codex")

        captured = {}

        async def fake_shell(cmd_str, **kwargs):
            captured["cmd"] = cmd_str
            proc = MagicMock()
            proc.communicate = AsyncMock(return_value=(b'{"result":"ok"}', b""))
            proc.returncode = 0
            return proc

        with patch("asyncio.create_subprocess_shell", side_effect=fake_shell):
            from tools.gimo_server.providers.cli_account import CliAccountAdapter
            adapter = CliAccountAdapter(binary="codex")
            await adapter.generate("hello", {})

        assert "codex" in captured["cmd"]
        assert "execute" in captured["cmd"]

    @pytest.mark.asyncio
    async def test_generate_uses_exec_on_linux(self, _fake_linux, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/codex")

        captured = {}

        async def fake_exec(*args, **kwargs):
            captured["args"] = args
            proc = MagicMock()
            proc.communicate = AsyncMock(return_value=(b'{"result":"ok"}', b""))
            proc.returncode = 0
            return proc

        with patch("asyncio.create_subprocess_exec", side_effect=fake_exec):
            from tools.gimo_server.providers.cli_account import CliAccountAdapter
            adapter = CliAccountAdapter(binary="codex")
            await adapter.generate("hello", {})

        assert captured["args"][0] == "codex"
        assert "cmd.exe" not in captured["args"]

    @pytest.mark.asyncio
    async def test_health_check_uses_shell_on_windows(self, _fake_win32, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: "/fake/codex")

        captured = {}

        async def fake_shell(cmd_str, **kwargs):
            captured["cmd"] = cmd_str
            proc = MagicMock()
            proc.communicate = AsyncMock(return_value=(b"0.113.0", b""))
            proc.returncode = 0
            return proc

        with patch("asyncio.create_subprocess_shell", side_effect=fake_shell):
            from tools.gimo_server.providers.cli_account import CliAccountAdapter
            adapter = CliAccountAdapter(binary="codex")
            result = await adapter.health_check()

        assert result is True
        assert "codex" in captured["cmd"]
        assert "--version" in captured["cmd"]


# ---------------------------------------------------------------------------
# codex_auth_service.py — start_device_flow
# ---------------------------------------------------------------------------

class TestCodexAuthServiceWindows:
    @pytest.mark.asyncio
    async def test_device_flow_uses_shell_on_windows(self, _fake_win32, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: "/fake/codex")

        captured = {}

        async def fake_shell(cmd_str, **kwargs):
            captured["cmd"] = cmd_str
            proc = MagicMock()
            proc.stdout = MagicMock()
            # Simulate codex outputting a URL and code
            lines = [
                b"Please open https://openai.com/device and enter the code: ABCD-1234\n",
                b"",
            ]
            proc.stdout.readline = AsyncMock(side_effect=lines)
            proc.wait = AsyncMock(return_value=0)
            proc.returncode = 0
            proc.kill = MagicMock()
            return proc

        with patch("asyncio.create_subprocess_shell", side_effect=fake_shell):
            from tools.gimo_server.services.codex_auth_service import CodexAuthService
            result = await CodexAuthService.start_device_flow()

        assert "codex login --device-auth" in captured["cmd"]
        assert result["status"] == "pending"
        assert result["verification_url"] == "https://openai.com/device"
        assert result["user_code"] == "ABCD-1234"

    @pytest.mark.asyncio
    async def test_device_flow_returns_error_when_cli_missing(self, monkeypatch):
        monkeypatch.setattr("tools.gimo_server.services.codex_auth_service.shutil.which", lambda _: None)
        from tools.gimo_server.services.codex_auth_service import CodexAuthService
        result = await CodexAuthService.start_device_flow()
        assert result["status"] == "error"
        assert "Codex CLI no detectado" in result["message"]


# ---------------------------------------------------------------------------
# provider_catalog_service.py — _validate_cli_account_provider
# ---------------------------------------------------------------------------

class TestCatalogValidateWindows:
    @pytest.mark.asyncio
    async def test_validate_cli_account_uses_shell_on_windows(self, _fake_win32, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _: "/fake/codex")

        captured = {}

        async def fake_shell(cmd_str, **kwargs):
            captured["cmd"] = cmd_str
            proc = MagicMock()
            proc.communicate = AsyncMock(return_value=(b"codex-cli 0.113.0", b""))
            proc.returncode = 0
            return proc

        with patch("asyncio.create_subprocess_shell", side_effect=fake_shell):
            from tools.gimo_server.services.provider_catalog_service import ProviderCatalogService
            result = await ProviderCatalogService._validate_cli_account_provider("codex")

        assert result.valid is True
        assert "codex" in captured["cmd"]
        assert "--version" in captured["cmd"]


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
            proc = MagicMock()
            proc.communicate = AsyncMock(return_value=(b"codex-cli 0.113.0", b""))
            proc.returncode = 0
            return proc

        with patch("asyncio.create_subprocess_shell", side_effect=fake_shell):
            from tools.gimo_server.services.provider_connector_service import ProviderConnectorService
            version = await ProviderConnectorService._resolve_cli_version("codex")

        assert version is not None
        assert "codex" in captured["cmd"]
