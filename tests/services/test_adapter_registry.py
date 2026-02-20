from __future__ import annotations

from unittest.mock import patch

from tools.gimo_server.adapters.codex import CodexAdapter
from tools.gimo_server.adapters.gemini import GeminiAdapter
from tools.gimo_server.adapters.openai_compatible import OpenAICompatibleAdapter
from tools.gimo_server.services.adapter_registry import AdapterRegistry


def setup_function() -> None:
    AdapterRegistry.reset()


def teardown_function() -> None:
    AdapterRegistry.reset()


def test_initialize_defaults_registers_local_and_available_cli_adapters() -> None:
    with patch(
        "tools.gimo_server.services.adapter_registry.shutil.which",
        side_effect=lambda binary: f"/usr/bin/{binary}" if binary in {"codex", "gemini"} else None,
    ):
        AdapterRegistry.initialize_defaults()

    local = AdapterRegistry.get("local")
    codex = AdapterRegistry.get("codex")
    gemini = AdapterRegistry.get("gemini")

    assert isinstance(local, OpenAICompatibleAdapter)
    assert isinstance(codex, CodexAdapter)
    assert isinstance(gemini, GeminiAdapter)

    assert AdapterRegistry.is_available("local") is True
    assert AdapterRegistry.is_available("codex") is True
    assert AdapterRegistry.is_available("gemini") is True


def test_initialize_defaults_marks_unavailable_cli_adapters_when_missing() -> None:
    with patch("tools.gimo_server.services.adapter_registry.shutil.which", return_value=None):
        AdapterRegistry.initialize_defaults()

    assert isinstance(AdapterRegistry.get("local"), OpenAICompatibleAdapter)
    assert AdapterRegistry.get("codex") is None
    assert AdapterRegistry.get("gemini") is None

    assert AdapterRegistry.is_available("local") is True
    assert AdapterRegistry.is_available("codex") is False
    assert AdapterRegistry.is_available("gemini") is False


def test_list_registered_returns_copy_not_live_reference() -> None:
    with patch("tools.gimo_server.services.adapter_registry.shutil.which", return_value=None):
        AdapterRegistry.initialize_defaults()

    snapshot = AdapterRegistry.list_registered()
    snapshot["intruder"] = object()

    assert "intruder" not in AdapterRegistry.list_registered()
