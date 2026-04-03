"""Tests for server-side X-Preferred-Model validation (Change 2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from unittest.mock import patch

import pytest


# Minimal stubs to test _resolve_effective_provider_and_model in isolation
@dataclass
class _FakeModelEntry:
    model_id: str
    provider_id: str
    provider_type: str = "openai"
    is_local: bool = False
    quality_tier: int = 3
    capabilities: set = field(default_factory=lambda: {"chat"})


@dataclass
class _FakeProviderEntry:
    model: str = "default-model"
    model_id: Optional[str] = None
    provider_type: Optional[str] = None
    type: str = "openai"
    capabilities: Optional[Dict] = None


@dataclass
class _FakeProviderConfig:
    active: str = "local_ollama"
    providers: Dict[str, Any] = field(default_factory=dict)


def _make_cfg(active="local_ollama", model="qwen2.5-coder:3b"):
    return _FakeProviderConfig(
        active=active,
        providers={active: _FakeProviderEntry(model=model)},
    )


class TestModelValidation:
    """Test the model validation logic added to _resolve_effective_provider_and_model."""

    def test_valid_model_passes_through(self):
        """Model that belongs to active provider should be used directly."""
        from tools.gimo_server.services.providers.service_impl import ProviderService
        from tools.gimo_server.services import model_inventory_service as mis_mod

        cfg = _make_cfg()
        entry = _FakeModelEntry(model_id="qwen2.5-coder:3b", provider_id="local_ollama")

        with patch.object(mis_mod.ModelInventoryService, "get_available_models", return_value=[entry]), \
             patch.object(mis_mod.ModelInventoryService, "find_model", return_value=entry):
            _provider, model = ProviderService._resolve_effective_provider_and_model(
                cfg, {"model": "qwen2.5-coder:3b"}, "disruptive_planning"
            )
            assert model == "qwen2.5-coder:3b"

    def test_wrong_provider_model_discarded(self):
        """Model belonging to different provider should be discarded."""
        from tools.gimo_server.services.providers.service_impl import ProviderService
        from tools.gimo_server.services import model_inventory_service as mis_mod

        cfg = _make_cfg()
        entry = _FakeModelEntry(model_id="claude-haiku", provider_id="claude-account")

        with patch.object(mis_mod.ModelInventoryService, "get_available_models", return_value=[entry]), \
             patch.object(mis_mod.ModelInventoryService, "find_model", return_value=entry):
            _provider, model = ProviderService._resolve_effective_provider_and_model(
                cfg, {"model": "claude-haiku"}, "disruptive_planning"
            )
            # Model should have been discarded; falls through to provider default
            assert model != "claude-haiku"

    def test_empty_inventory_passes_through(self):
        """When inventory is empty (cold start), model passes through unchanged."""
        from tools.gimo_server.services.providers.service_impl import ProviderService
        from tools.gimo_server.services import model_inventory_service as mis_mod

        cfg = _make_cfg()

        with patch.object(mis_mod.ModelInventoryService, "get_available_models", return_value=[]):
            _provider, model = ProviderService._resolve_effective_provider_and_model(
                cfg, {"model": "anything-goes"}, "disruptive_planning"
            )
            assert model == "anything-goes"

    def test_low_tier_model_still_passes(self):
        """Low-tier model should warn but still pass through (not block)."""
        from tools.gimo_server.services.providers.service_impl import ProviderService
        from tools.gimo_server.services import model_inventory_service as mis_mod

        cfg = _make_cfg(model="tiny-1b")
        entry = _FakeModelEntry(model_id="tiny-1b", provider_id="local_ollama", quality_tier=1)

        with patch.object(mis_mod.ModelInventoryService, "get_available_models", return_value=[entry]), \
             patch.object(mis_mod.ModelInventoryService, "find_model", return_value=entry):
            _provider, model = ProviderService._resolve_effective_provider_and_model(
                cfg, {"model": "tiny-1b"}, "agentic_chat"
            )
            # Should still use the model (warn, don't block)
            assert model == "tiny-1b"

    def test_no_preferred_model_unchanged(self):
        """When no model preference, normal routing runs."""
        from tools.gimo_server.services.providers.service_impl import ProviderService
        from tools.gimo_server.services import model_inventory_service as mis_mod
        from tools.gimo_server.services import model_router_service as mr_mod

        cfg = _make_cfg()
        binding = type("Binding", (), {"provider_id": "local_ollama", "model": "routed-model"})()

        with patch.object(mis_mod.ModelInventoryService, "get_available_models", return_value=[]), \
             patch.object(mr_mod.ModelRouterService, "choose_binding_from_candidates", return_value=binding):
            _provider, model = ProviderService._resolve_effective_provider_and_model(
                cfg, {}, "disruptive_planning"
            )
            assert model is not None
