"""Compliance tests — verify SAGP policy alignment.

These tests ensure GIMO does NOT use CliAccountAdapter for Claude
and that the new SAGP components are structurally correct.
"""

import os

import pytest


class TestCliAccountAdapterCompliance:
    """Verify Claude CLI account mode is blocked."""

    def test_adapter_registry_blocks_claude_account_without_key(self, monkeypatch):
        """CliAccountAdapter for Claude must raise ValueError when no API key."""
        from tools.gimo_server.services.providers.adapter_registry import build_provider_adapter
        from tools.gimo_server.ops_models import ProviderEntry

        # Ensure no ANTHROPIC_API_KEY leaks from other tests
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        entry = ProviderEntry(
            type="claude",
            provider_type="claude",
            display_name="Claude Account",
            auth_mode="account",
            model="claude-sonnet-4-6",
            model_id="claude-sonnet-4-6",
        )

        with pytest.raises(ValueError, match="no longer supported"):
            build_provider_adapter(
                entry=entry,
                canonical_type="claude",
                resolve_secret=lambda e: None,  # No API key
            )

    def test_adapter_registry_allows_codex_account(self, monkeypatch):
        """Codex CLI account mode must still work."""
        from tools.gimo_server.services.providers.adapter_registry import build_provider_adapter
        from tools.gimo_server.ops_models import ProviderEntry
        from tools.gimo_server.providers.cli_account import CliAccountAdapter

        # Ensure no API key leak from other tests affects codex path
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        entry = ProviderEntry(
            type="codex",
            provider_type="codex",
            display_name="Codex Account",
            auth_mode="account",
            model="gpt-5-codex",
            model_id="gpt-5-codex",
        )

        adapter = build_provider_adapter(
            entry=entry,
            canonical_type="codex",
            resolve_secret=lambda e: None,
        )
        # Use class name check to avoid module identity mismatch in test runner
        assert type(adapter).__name__ == "CliAccountAdapter"

    def test_adapter_registry_allows_claude_with_api_key(self):
        """Claude with API key must use AnthropicAdapter, not CliAccountAdapter."""
        from tools.gimo_server.services.providers.adapter_registry import build_provider_adapter
        from tools.gimo_server.ops_models import ProviderEntry
        from tools.gimo_server.providers.anthropic_adapter import AnthropicAdapter

        entry = ProviderEntry(
            type="claude",
            provider_type="claude",
            display_name="Claude API",
            auth_mode="account",
            model="claude-sonnet-4-6",
            model_id="claude-sonnet-4-6",
        )

        adapter = build_provider_adapter(
            entry=entry,
            canonical_type="claude",
            resolve_secret=lambda e: "sk-ant-test-key",
        )
        assert type(adapter).__name__ == "AnthropicAdapter"


class TestSagpModelsExist:
    """Verify SAGP models are importable and correct."""

    def test_surface_identity_importable(self):
        from tools.gimo_server.models.surface import SurfaceIdentity
        s = SurfaceIdentity(surface_type="cli", surface_name="test")
        assert s.surface_type == "cli"

    def test_governance_verdict_importable(self):
        from tools.gimo_server.models.governance import GovernanceVerdict
        v = GovernanceVerdict(
            allowed=True,
            policy_name="read_only",
            risk_band="low",
            trust_score=0.9,
            estimated_cost_usd=0.0,
            requires_approval=False,
            circuit_breaker_state="closed",
            proof_id="test",
            reasoning="ok",
        )
        assert v.allowed is True

    def test_sagp_gateway_importable(self):
        from tools.gimo_server.services.sagp_gateway import SagpGateway
        assert hasattr(SagpGateway, "evaluate_action")
        assert hasattr(SagpGateway, "get_snapshot")

    def test_contract_has_surface_field(self):
        from tools.gimo_server.models.contract import GimoContract
        from dataclasses import fields
        field_names = {f.name for f in fields(GimoContract)}
        assert "surface" in field_names
