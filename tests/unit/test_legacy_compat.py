"""P10 — Legacy Data Compatibility tests."""
import json
import pytest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from tools.gimo_server.models.core import OpsRun
from tools.gimo_server.models.plan import PlanNode, CustomPlan
from tools.gimo_server.models.agent_routing import (
    RoutingDecision,
    ModelBinding,
    ResolvedAgentProfile,
)
from tools.gimo_server.services.plan_migration_service import PlanMigrationService


# ── Gap 1: OpsRun routing fields ──


class TestOpsRunRoutingFields:
    def test_ops_run_routing_fields_roundtrip(self):
        """Create OpsRun with routing fields, serialize/deserialize, verify."""
        snapshot = {
            "profile": {"agent_preset": "executor", "task_role": "executor"},
            "binding": {"provider": "openai", "model": "gpt-4"},
        }
        run = OpsRun(
            id="r_test1",
            approved_id="a_test1",
            agent_preset="executor",
            execution_policy_name="workspace_safe",
            routing_snapshot=snapshot,
        )
        assert run.agent_preset == "executor"
        assert run.execution_policy_name == "workspace_safe"
        assert run.routing_snapshot == snapshot

        # Round-trip through JSON
        raw = run.model_dump_json()
        restored = OpsRun.model_validate_json(raw)
        assert restored.agent_preset == "executor"
        assert restored.execution_policy_name == "workspace_safe"
        assert restored.routing_snapshot == snapshot

    def test_ops_run_legacy_json_graceful(self):
        """Deserialize old JSON without routing fields — defaults to None."""
        legacy_json = json.dumps({
            "id": "r_old",
            "approved_id": "a_old",
            "status": "done",
            "log": [],
            "created_at": "2026-03-01T00:00:00+00:00",
        })
        run = OpsRun.model_validate_json(legacy_json)
        assert run.agent_preset is None
        assert run.execution_policy_name is None
        assert run.routing_snapshot is None


# ── Gap 2: Save guard ──


class TestSaveGuard:
    def test_save_guard_migrates_v1_nodes(self, tmp_path):
        """Plan with v1 nodes — _save() should produce v2 JSON with routing_decision."""
        from tools.gimo_server.services.custom_plan_service import CustomPlanService

        # Create a v1.0 node (no routing_decision)
        v1_node = PlanNode(
            id="orch",
            label="Orchestrator",
            prompt="",
            role="orchestrator",
            node_type="orchestrator",
            is_orchestrator=True,
            model="gpt-4",
            provider="openai",
            agent_preset="executor",
        )
        assert v1_node.routing_decision is None

        plan = CustomPlan(
            id="plan_test_save",
            name="Test",
            nodes=[v1_node],
            edges=[],
        )

        plan_path = tmp_path / f"{plan.id}.json"
        with patch.object(CustomPlanService, "_plan_path", return_value=plan_path):
            CustomPlanService._save(plan)

        # Read raw JSON (no model parsing) to verify routing_decision persisted
        raw = json.loads(plan_path.read_text(encoding="utf-8"))
        node_raw = raw["nodes"][0]
        assert node_raw.get("routing_decision") is not None
        assert node_raw["routing_decision"]["profile"]["agent_preset"] == "executor"

    def test_save_guard_idempotent_v2(self, tmp_path):
        """Plan with v2 nodes — _save() should not mutate."""
        from tools.gimo_server.services.custom_plan_service import CustomPlanService

        profile = ResolvedAgentProfile(
            agent_preset="plan_orchestrator",
            task_role="orchestrator",
            mood="neutral",
            execution_policy="workspace_safe",
            workflow_phase="planning",
        )
        binding = ModelBinding(
            provider="anthropic",
            model="claude-3",
            binding_mode="plan_time",
            binding_reason="test",
        )
        rd = RoutingDecision(
            profile=profile,
            binding=binding,
            routing_reason="test_direct",
            candidate_count=1,
        )
        v2_node = PlanNode(
            id="orch",
            label="Orchestrator",
            prompt="",
            role="orchestrator",
            node_type="orchestrator",
            is_orchestrator=True,
            routing_decision=rd,
        )

        plan = CustomPlan(
            id="plan_test_idem",
            name="Test Idem",
            nodes=[v2_node],
            edges=[],
        )

        plan_path = tmp_path / f"{plan.id}.json"
        with patch.object(CustomPlanService, "_plan_path", return_value=plan_path):
            CustomPlanService._save(plan)

        raw = json.loads(plan_path.read_text(encoding="utf-8"))
        node_raw = raw["nodes"][0]
        assert node_raw["routing_decision"]["profile"]["agent_preset"] == "plan_orchestrator"
        assert node_raw["routing_decision"]["binding"]["provider"] == "anthropic"
        assert node_raw["routing_decision"]["routing_reason"] == "test_direct"


# ── Gap 3: Audit methods ──


class TestAuditMigrationStatus:
    def test_audit_migration_status_empty(self, tmp_path):
        """No plans dir — should return clean response."""
        with patch("tools.gimo_server.services.plan_migration_service.PlanMigrationService.audit_migration_status") as mock_audit:
            # Simulate by calling real method with patched OPS_DATA_DIR
            pass

        # Direct test: patch OPS_DATA_DIR to tmp_path (no custom_plans subdir)
        with patch("tools.gimo_server.config.OPS_DATA_DIR", tmp_path):
            result = PlanMigrationService.audit_migration_status()

        assert result["total_plans"] == 0
        assert result["total_nodes"] == 0
        assert result["v1_nodes"] == 0
        assert result["v2_nodes"] == 0
        assert result["migration_complete"] is True
        assert result["plans_with_legacy"] == []

    def test_audit_migration_status_mixed(self, tmp_path):
        """Write raw JSON v1/v2 plans, verify counts."""
        plans_dir = tmp_path / "custom_plans"
        plans_dir.mkdir()

        # Plan with 1 v2 node and 1 v1 node
        plan_a = {
            "id": "plan_a",
            "name": "A",
            "nodes": [
                {"id": "n1", "label": "N1", "routing_decision": {"profile": {}, "binding": {}}},
                {"id": "n2", "label": "N2"},  # v1 — no routing_decision
            ],
            "edges": [],
        }
        # Plan with all v2 nodes
        plan_b = {
            "id": "plan_b",
            "name": "B",
            "nodes": [
                {"id": "n3", "label": "N3", "routing_decision": {"profile": {}, "binding": {}}},
            ],
            "edges": [],
        }

        (plans_dir / "plan_a.json").write_text(json.dumps(plan_a), encoding="utf-8")
        (plans_dir / "plan_b.json").write_text(json.dumps(plan_b), encoding="utf-8")

        with patch("tools.gimo_server.config.OPS_DATA_DIR", tmp_path):
            result = PlanMigrationService.audit_migration_status()

        assert result["total_plans"] == 2
        assert result["total_nodes"] == 3
        assert result["v1_nodes"] == 1
        assert result["v2_nodes"] == 2
        assert result["migration_complete"] is False
        assert "plan_a" in result["plans_with_legacy"]

    def test_audit_run_routing_coverage(self, tmp_path):
        """Verify run routing coverage counts."""
        runs_dir = tmp_path / "runs"
        runs_dir.mkdir()

        # Run with routing metadata
        run_a = {"id": "r_a", "agent_preset": "executor", "status": "done"}
        # Run without routing metadata
        run_b = {"id": "r_b", "status": "done"}
        # Run with empty agent_preset (treated as without)
        run_c = {"id": "r_c", "agent_preset": "", "status": "done"}

        (runs_dir / "r_a.json").write_text(json.dumps(run_a), encoding="utf-8")
        (runs_dir / "r_b.json").write_text(json.dumps(run_b), encoding="utf-8")
        (runs_dir / "r_c.json").write_text(json.dumps(run_c), encoding="utf-8")

        with patch("tools.gimo_server.config.OPS_DATA_DIR", tmp_path):
            result = PlanMigrationService.audit_run_routing_coverage()

        assert result["total_runs"] == 3
        assert result["with_routing_metadata"] == 1
        assert result["without_routing_metadata"] == 2
        assert result["coverage_pct"] == 33.3
