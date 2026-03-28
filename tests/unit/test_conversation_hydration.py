"""Tests for ConversationService hydration and derivation logic."""

import pytest
from tools.gimo_server.services.conversation_service import ConversationService


def test_derive_workflow_phase_intake_with_approved_plan():
    """_derive_workflow_phase returns 'executing' when plan is approved."""
    phase = ConversationService._derive_workflow_phase(
        raw_phase="intake",
        proposed_plan={"id": "pl_test"},
        metadata={"plan_approved": True},
    )
    assert phase == "executing"


def test_derive_workflow_phase_intake_with_pending_plan():
    """_derive_workflow_phase returns 'awaiting_approval' when plan exists but not approved."""
    phase = ConversationService._derive_workflow_phase(
        raw_phase="intake",
        proposed_plan={"id": "pl_test"},
        metadata={},
    )
    assert phase == "awaiting_approval"


def test_derive_workflow_phase_no_plan():
    """_derive_workflow_phase returns intake when no plan exists."""
    phase = ConversationService._derive_workflow_phase(
        raw_phase=None,
        proposed_plan=None,
        metadata={},
    )
    assert phase == "intake"


def test_derive_profile_summary_from_preset():
    """_derive_profile_summary builds ProfileSummary from agent_preset."""
    summary = ConversationService._derive_profile_summary(
        agent_preset="researcher",
        legacy_mood=None,
        workflow_phase="intake",
        metadata={},
    )
    assert summary.agent_preset == "researcher"
    assert summary.task_role == "researcher"
    assert summary.mood == "analytical"
    assert summary.execution_policy == "docs_research"
    assert summary.workflow_phase == "intake"


def test_derive_profile_summary_fallback_from_mood():
    """_derive_profile_summary derives from legacy_mood when agent_preset is None."""
    summary = ConversationService._derive_profile_summary(
        agent_preset=None,
        legacy_mood="forensic",
        workflow_phase="planning",
        metadata={},
    )
    # forensic → researcher preset
    assert summary.agent_preset == "researcher"
    assert summary.mood == "analytical"
    assert summary.execution_policy == "docs_research"


def test_hydrate_thread_sets_profile_summary():
    """_hydrate_thread sets agent_preset and workflow_phase from raw_data."""
    from tools.gimo_server.ops_models import GimoThread

    thread = GimoThread(
        id="th_test",
        label="Test",
        status="active",
        agent_preset="plan_orchestrator",
        workflow_phase="intake",
        workspace_root="/tmp/test",
    )

    raw_data = {
        "agent_preset": "researcher",
        "mood": "analytical",
        "workflow_phase": "planning",
    }

    ConversationService._hydrate_thread(thread, raw_data)

    assert thread.agent_preset == "researcher"
    assert thread.workflow_phase in ["planning", "intake", "awaiting_approval", "executing"]
    assert thread.profile_summary is not None
    assert thread.profile_summary.agent_preset == "researcher"
