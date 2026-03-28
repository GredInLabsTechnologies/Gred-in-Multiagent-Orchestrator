"""Tests for AgentCatalogService — preset resolution and profile hydration."""

import pytest
from tools.gimo_server.services.agent_catalog_service import AgentCatalogService


def test_preset_for_legacy_mood_forensic():
    """Legacy mood 'forensic' maps to preset 'researcher'."""
    preset_name = AgentCatalogService.preset_for_legacy_mood("forensic")
    assert preset_name == "researcher"


def test_preset_for_legacy_mood_unknown_raises():
    """Unknown legacy mood raises KeyError."""
    with pytest.raises(KeyError):
        AgentCatalogService.preset_for_legacy_mood("unknown_mood_123")


def test_resolve_profile_uses_preset_policy():
    """resolve_profile constructs profile with preset's execution_policy."""
    profile = AgentCatalogService.resolve_profile(
        agent_preset="researcher",
        legacy_mood=None,
        workflow_phase="intake",
    )
    assert profile.agent_preset == "researcher"
    assert profile.execution_policy == "docs_research"
    assert profile.task_role == "researcher"
    assert profile.mood == "analytical"
    assert profile.workflow_phase == "intake"


def test_get_mood_canonical_and_legacy():
    """get_mood resolves both canonical and legacy mood names."""
    # Canonical
    analytical = AgentCatalogService.get_mood("analytical")
    assert analytical.name == "analytical"
    assert analytical.temperature >= 0  # analytical has temp=0.0

    # Legacy alias
    forensic = AgentCatalogService.get_mood("forensic")
    assert forensic.name == "analytical"  # canonical name
    assert forensic.temperature == analytical.temperature


def test_resolve_profile_from_legacy_mood():
    """resolve_profile can derive preset from legacy_mood when preset is None."""
    profile = AgentCatalogService.resolve_profile(
        agent_preset=None,
        legacy_mood="forensic",
        workflow_phase="planning",
    )
    assert profile.agent_preset == "researcher"
    assert profile.mood == "analytical"
    assert profile.workflow_phase == "planning"
