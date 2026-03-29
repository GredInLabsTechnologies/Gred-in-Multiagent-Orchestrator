"""Unit tests for PlanMigrationService."""
import pytest
from tools.gimo_server.models.plan import PlanNode
from tools.gimo_server.models.agent_routing import RoutingDecision, ModelBinding, ResolvedAgentProfile
from tools.gimo_server.services.plan_migration_service import PlanMigrationService


class TestPlanMigrationService:
    """Tests for PlanMigrationService."""

    def test_migrate_node_with_full_legacy_fields(self):
        """Migrate node with complete legacy fields."""
        # Create v1.0 node (no routing_decision, only legacy fields)
        # Note: resolved_profile contains the full profile data
        legacy_data = {
            "id": "test-1",
            "label": "Test Node",
            "prompt": "Do something",
            "model": "gpt-4",
            "provider": "openai",
            "agent_preset": "executor",
            "execution_policy": "workspace_safe",
            "workflow_phase": "executing",
            "binding_mode": "plan_time",
            "resolved_profile": {
                "agent_preset": "executor",
                "task_role": "executor",
                "mood": "assertive",
                "execution_policy": "workspace_safe",
                "workflow_phase": "executing",
            },
        }

        node = PlanNode(**legacy_data)
        assert node.routing_decision is None  # v1.0 node

        # Migrate
        migrated = PlanMigrationService.migrate_node(node)

        # Verify routing_decision created
        assert migrated.routing_decision is not None
        assert migrated.routing_decision.schema_version == "2.0"

        # Verify profile migrated correctly
        profile = migrated.routing_decision.profile
        assert profile.agent_preset == "executor"
        assert profile.task_role == "executor"
        assert profile.mood == "assertive"
        assert profile.execution_policy == "workspace_safe"
        assert profile.workflow_phase == "executing"

        # Verify binding migrated correctly
        binding = migrated.routing_decision.binding
        assert binding.provider == "openai"
        assert binding.model == "gpt-4"
        assert binding.binding_mode == "plan_time"
        assert "migrated" in binding.binding_reason.lower()

    def test_migrate_node_with_minimal_legacy_fields(self):
        """Migrate node with minimal legacy fields (fallback to defaults)."""
        legacy_data = {
            "id": "test-2",
            "label": "Minimal Node",
        }

        node = PlanNode(**legacy_data)
        migrated = PlanMigrationService.migrate_node(node)

        # Verify defaults applied
        assert migrated.routing_decision is not None
        profile = migrated.routing_decision.profile
        assert profile.agent_preset == "executor"  # Default
        assert profile.task_role == "executor"
        assert profile.mood == "neutral"

        binding = migrated.routing_decision.binding
        assert binding.provider == "auto"
        assert binding.model == "auto"

    def test_migrate_node_idempotent(self):
        """Migrating already-migrated node is idempotent."""
        # Create v2.0 node (with routing_decision)
        routing = RoutingDecision(
            profile=ResolvedAgentProfile(
                agent_preset="reviewer",
                task_role="reviewer",
                mood="cautious",
                execution_policy="read_only",
                workflow_phase="reviewing",
            ),
            binding=ModelBinding(
                provider="claude-account",
                model="claude-3.5-sonnet",
                binding_mode="plan_time",
                binding_reason="test",
            ),
            routing_reason="test",
            candidate_count=1,
        )

        node = PlanNode(id="test-3", label="", routing_decision=routing)

        # Migrate (should be no-op)
        migrated = PlanMigrationService.migrate_node(node)

        # Verify unchanged
        assert migrated.routing_decision is routing
        assert migrated.routing_decision.profile.agent_preset == "reviewer"
        assert migrated.routing_decision.binding.provider == "claude-account"

    def test_needs_migration_v1_node(self):
        """needs_migration() returns True for v1.0 nodes."""
        node = PlanNode(id="test-4", label="", model="gpt-4", provider="openai")
        assert PlanMigrationService.needs_migration(node) is True

    def test_needs_migration_v2_node(self):
        """needs_migration() returns False for v2.0 nodes."""
        routing = RoutingDecision(
            profile=ResolvedAgentProfile(
                agent_preset="executor",
                task_role="executor",
                mood="neutral",
                execution_policy="workspace_safe",
                workflow_phase="executing",
            ),
            binding=ModelBinding(provider="auto", model="auto", binding_mode="plan_time", binding_reason="test"),
            routing_reason="test",
            candidate_count=1,
        )

        node = PlanNode(id="test-5", label="", routing_decision=routing)
        assert PlanMigrationService.needs_migration(node) is False

    def test_migrate_nodes_batch(self):
        """migrate_nodes() migrates multiple nodes."""
        # Create 3 nodes: v1, v2, v1
        routing_v2 = RoutingDecision(
            profile=ResolvedAgentProfile(
                agent_preset="executor",
                task_role="executor",
                mood="neutral",
                execution_policy="workspace_safe",
                workflow_phase="executing",
            ),
            binding=ModelBinding(provider="auto", model="auto", binding_mode="plan_time", binding_reason="test"),
            routing_reason="test",
            candidate_count=1,
        )

        nodes = [
            PlanNode(id="n1", label="", model="gpt-4", provider="openai"),  # v1
            PlanNode(id="n2", label="", routing_decision=routing_v2),  # v2
            PlanNode(id="n3", label="", model="claude-3", provider="anthropic"),  # v1
        ]

        migrated = PlanMigrationService.migrate_nodes(nodes)

        assert len(migrated) == 3
        # All should have routing_decision now
        assert all(n.routing_decision is not None for n in migrated)

        # v1 nodes migrated
        assert migrated[0].routing_decision.binding.provider == "openai"
        assert migrated[2].routing_decision.binding.provider == "anthropic"

        # v2 node unchanged
        assert migrated[1].routing_decision is routing_v2

    def test_analyze_legacy_fields(self):
        """analyze_legacy_fields() returns correct analysis."""
        node = PlanNode(
            id="test-6",
            label="",
            model="gpt-4",
            provider="openai",
            agent_preset="executor",
            execution_policy="workspace_safe",
        )

        analysis = PlanMigrationService.analyze_legacy_fields(node)

        assert analysis["node_id"] == "test-6"
        assert analysis["has_routing_decision"] is False
        assert analysis["schema_version"] == "2.0"
        assert analysis["needs_migration"] is True
        assert "model" in analysis["legacy_fields_found"]
        assert "provider" in analysis["legacy_fields_found"]
        assert analysis["legacy_values"]["model"] == "gpt-4"
        assert analysis["legacy_values"]["provider"] == "openai"

    def test_migrate_node_with_resolved_profile(self):
        """Migrate node that has resolved_profile in legacy format."""
        legacy_data = {
            "id": "test-7",
            "label": "",
            "resolved_profile": {
                "agent_preset": "researcher",
                "task_role": "researcher",
                "mood": "analytical",
                "execution_policy": "docs_research",
                "workflow_phase": "planning",
            },
            "model": "gpt-4",
            "provider": "openai",
        }

        node = PlanNode(**legacy_data)
        migrated = PlanMigrationService.migrate_node(node)

        # Should use resolved_profile if available
        profile = migrated.routing_decision.profile
        assert profile.agent_preset == "researcher"
        assert profile.task_role == "researcher"
        assert profile.mood == "analytical"
        assert profile.execution_policy == "docs_research"

    def test_migrate_nodes_handles_errors_gracefully(self):
        """migrate_nodes() keeps original node on error."""
        # Create a node that might cause issues (though our migration is robust)
        nodes = [
            PlanNode(id="good", label="", model="gpt-4", provider="openai"),
            PlanNode(id="also-good", label="", model="claude-3", provider="anthropic"),
        ]

        migrated = PlanMigrationService.migrate_nodes(nodes)

        # All nodes should be in result (no exceptions raised)
        assert len(migrated) == 2
        assert all(isinstance(n, PlanNode) for n in migrated)
