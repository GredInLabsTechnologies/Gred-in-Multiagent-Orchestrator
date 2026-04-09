"""Unit tests for SAGP Gateway — governance verdict correctness, policy gating, cost estimation."""

import pytest
from unittest.mock import patch

from tools.gimo_server.models.governance import GovernanceSnapshot, GovernanceVerdict
from tools.gimo_server.models.surface import SurfaceIdentity
from tools.gimo_server.services.sagp_gateway import SagpGateway
from tools.gimo_server.security.execution_proof import ExecutionProofChain


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def surface():
    return SurfaceIdentity(
        surface_type="cli",
        surface_name="test-surface",
        capabilities=frozenset({"streaming", "hitl_inline"}),
    )


@pytest.fixture()
def mcp_surface():
    return SurfaceIdentity(
        surface_type="mcp_generic",
        surface_name="test-mcp",
    )


# ---------------------------------------------------------------------------
# GovernanceVerdict tests
# ---------------------------------------------------------------------------


class TestGovernanceVerdict:
    def test_verdict_to_dict_has_all_fields(self):
        verdict = GovernanceVerdict(
            allowed=True,
            policy_name="workspace_safe",
            risk_band="low",
            trust_score=0.85,
            estimated_cost_usd=0.001,
            requires_approval=False,
            circuit_breaker_state="closed",
            proof_id="abc123",
            reasoning="Allowed",
            constraints=("fs:workspace_only",),
        )
        d = verdict.to_dict()
        assert d["allowed"] is True
        assert d["policy_name"] == "workspace_safe"
        assert d["risk_band"] == "low"
        assert isinstance(d["constraints"], list)
        assert "fs:workspace_only" in d["constraints"]

    def test_verdict_is_frozen(self):
        verdict = GovernanceVerdict(
            allowed=True,
            policy_name="read_only",
            risk_band="low",
            trust_score=0.9,
            estimated_cost_usd=0.0,
            requires_approval=False,
            circuit_breaker_state="closed",
            proof_id="x",
            reasoning="ok",
        )
        with pytest.raises(AttributeError):
            verdict.allowed = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# GovernanceSnapshot tests
# ---------------------------------------------------------------------------


class TestGovernanceSnapshot:
    def test_snapshot_to_dict(self):
        snap = GovernanceSnapshot(
            surface_type="cli",
            surface_name="test",
            active_policy="workspace_safe",
            trust_profile={"provider": 0.9, "model": 0.8},
            proof_chain_length=5,
        )
        d = snap.to_dict()
        assert d["surface_type"] == "cli"
        assert d["proof_chain_length"] == 5
        assert "timestamp" in d


# ---------------------------------------------------------------------------
# SurfaceIdentity tests
# ---------------------------------------------------------------------------


class TestSurfaceIdentity:
    def test_capabilities_query(self):
        s = SurfaceIdentity(
            surface_type="claude_app",
            surface_name="test",
            capabilities=frozenset({"streaming", "mcp_apps", "agent_teams"}),
        )
        assert s.supports_streaming is True
        assert s.supports_mcp_apps is True
        assert s.supports_agent_teams is True
        assert s.supports_hitl is False

    def test_surface_is_frozen(self):
        s = SurfaceIdentity(surface_type="cli", surface_name="test")
        with pytest.raises(AttributeError):
            s.surface_type = "web"  # type: ignore[misc]

    def test_default_capabilities_empty(self):
        s = SurfaceIdentity(surface_type="mcp_generic", surface_name="test")
        assert s.capabilities == frozenset()
        assert s.supports_streaming is False


# ---------------------------------------------------------------------------
# SagpGateway.evaluate_action tests
# ---------------------------------------------------------------------------


class TestEvaluateAction:
    def test_allowed_action_returns_allowed(self, surface):
        verdict = SagpGateway.evaluate_action(
            surface=surface,
            tool_name="read_file",
            policy_name="workspace_safe",
        )
        assert verdict.allowed is True
        assert verdict.policy_name == "workspace_safe"
        assert verdict.circuit_breaker_state == "closed"

    def test_read_only_policy_blocks_write(self, surface):
        verdict = SagpGateway.evaluate_action(
            surface=surface,
            tool_name="write_file",
            policy_name="read_only",
        )
        assert verdict.allowed is False
        assert "not allowed" in verdict.reasoning.lower()

    def test_high_risk_requires_approval(self, surface):
        verdict = SagpGateway.evaluate_action(
            surface=surface,
            tool_name="shell_exec",
            policy_name="docs_research",
        )
        assert verdict.requires_approval is True

    def test_verdict_has_proof_id(self, surface):
        verdict = SagpGateway.evaluate_action(
            surface=surface,
            tool_name="list_files",
            policy_name="read_only",
        )
        assert verdict.proof_id
        assert len(verdict.proof_id) > 0

    def test_cost_estimation_nonzero_for_known_model(self, surface):
        verdict = SagpGateway.evaluate_action(
            surface=surface,
            tool_name="read_file",
            tool_args={"model": "gpt-4o", "input_tokens": 5000, "output_tokens": 2000},
            policy_name="workspace_safe",
        )
        assert verdict.estimated_cost_usd > 0

    def test_default_policy_is_workspace_safe(self, surface):
        verdict = SagpGateway.evaluate_action(
            surface=surface,
            tool_name="read_file",
        )
        assert verdict.policy_name == "workspace_safe"

    def test_constraints_include_fs_mode(self, surface):
        verdict = SagpGateway.evaluate_action(
            surface=surface,
            tool_name="read_file",
            policy_name="read_only",
        )
        assert any("fs:" in c for c in verdict.constraints)


# ---------------------------------------------------------------------------
# SagpGateway.get_snapshot tests
# ---------------------------------------------------------------------------


class TestGetSnapshot:
    def test_snapshot_has_surface_info(self, surface):
        snapshot = SagpGateway.get_snapshot(surface=surface)
        assert snapshot.surface_type == "cli"
        assert snapshot.surface_name == "test-surface"

    def test_snapshot_has_trust_profile(self, surface):
        snapshot = SagpGateway.get_snapshot(surface=surface)
        assert "provider" in snapshot.trust_profile
        assert "model" in snapshot.trust_profile

    def test_snapshot_active_policy(self, mcp_surface):
        snapshot = SagpGateway.get_snapshot(surface=mcp_surface)
        assert snapshot.active_policy == "workspace_safe"


# ---------------------------------------------------------------------------
# SagpGateway.get_gics_insight tests
# ---------------------------------------------------------------------------


class TestGicsInsight:
    def test_gics_returns_dict(self):
        result = SagpGateway.get_gics_insight(prefix="test:", limit=5)
        assert isinstance(result, dict)
        assert "entries" in result or "error" in result


class TestProofVerification:
    def test_verify_proof_chain_empty_reports_absent(self):
        class _Storage:
            def list_proofs(self, _thread_id):
                return []

        with patch("tools.gimo_server.services.storage_service.StorageService", return_value=_Storage()):
            result = SagpGateway.verify_proof_chain(thread_id="thread-empty")

        assert result["thread_id"] == "thread-empty"
        assert result["state"] == "absent"
        assert result["valid"] is False
        assert result["length"] == 0

    def test_verify_proof_chain_present_includes_subject_and_executor(self):
        chain = ExecutionProofChain("thread-present")
        chain.append("write_file", {"path": "a.py"}, {"status": "success"}, mood="executor")
        records = [proof.to_dict() for proof in chain.to_list()]

        class _Storage:
            def list_proofs(self, _thread_id):
                return records

        with patch("tools.gimo_server.services.storage_service.StorageService", return_value=_Storage()):
            result = SagpGateway.verify_proof_chain(thread_id="thread-present")

        assert result["state"] == "present"
        assert result["valid"] is True
        assert result["subject"] == {"type": "thread", "id": "thread-present"}
        assert result["executor"] == {"type": "tool", "id": "write_file"}
