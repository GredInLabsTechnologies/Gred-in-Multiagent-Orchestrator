"""Unit tests for SchemaEvolutionService."""
import pytest
from tools.gimo_server.services.schema_evolution_service import SchemaEvolutionService


class TestSchemaEvolutionService:
    """Tests for SchemaEvolutionService."""

    def test_get_current_version_routing_decision(self):
        """get_current_version returns 2.0 for RoutingDecision."""
        version = SchemaEvolutionService.get_current_version("RoutingDecision")
        assert version == "2.0"

    def test_get_current_version_plan_node(self):
        """get_current_version returns 2.0 for PlanNode."""
        version = SchemaEvolutionService.get_current_version("PlanNode")
        assert version == "2.0"

    def test_get_current_version_unknown_schema(self):
        """get_current_version returns 1.0 for unknown schema."""
        version = SchemaEvolutionService.get_current_version("UnknownSchema")
        assert version == "1.0"

    def test_is_compatible_routing_decision_1_to_2(self):
        """RoutingDecision v1→v2 is backward compatible."""
        compatible = SchemaEvolutionService.is_compatible("RoutingDecision", "1.0", "2.0")
        assert compatible is True

    def test_is_compatible_plan_node_1_to_2(self):
        """PlanNode v1→v2 is backward compatible."""
        compatible = SchemaEvolutionService.is_compatible("PlanNode", "1.0", "2.0")
        assert compatible is True

    def test_is_compatible_unknown_schema(self):
        """Unknown schema returns False for compatibility."""
        compatible = SchemaEvolutionService.is_compatible("UnknownSchema", "1.0", "2.0")
        assert compatible is False

    def test_migrate_routing_decision_1_to_2(self):
        """Migrate RoutingDecision v1.0 → v2.0."""
        v1_data = {
            "resolved_profile": {
                "agent_preset": "executor",
                "task_role": "executor",
                "mood": "assertive",
                "execution_policy": "workspace_safe",
                "workflow_phase": "executing",
            },
            "provider": "openai",
            "model": "gpt-4",
            "binding_mode": "plan_time",
            "routing_reason": "test routing",
            "candidate_count": 3,
        }

        v2_data = SchemaEvolutionService.migrate(v1_data, "1.0", "2.0", "RoutingDecision")

        # Verify v2 structure
        assert v2_data["schema_version"] == "2.0"
        assert "profile" in v2_data
        assert "binding" in v2_data

        # Verify profile migrated
        profile = v2_data["profile"]
        assert profile["agent_preset"] == "executor"
        assert profile["task_role"] == "executor"
        assert profile["mood"] == "assertive"
        assert profile["execution_policy"] == "workspace_safe"
        assert profile["workflow_phase"] == "executing"

        # Verify binding migrated
        binding = v2_data["binding"]
        assert binding["provider"] == "openai"
        assert binding["model"] == "gpt-4"
        assert binding["binding_mode"] == "plan_time"
        assert "migrated" in binding["binding_reason"]

        # Verify other fields
        assert v2_data["routing_reason"] == "test routing"
        assert v2_data["candidate_count"] == 3

    def test_migrate_routing_decision_1_to_2_with_summary(self):
        """Migrate RoutingDecision v1.0 with summary instead of resolved_profile."""
        v1_data = {
            "summary": {
                "agent_preset": "researcher",
                "task_role": "researcher",
                "mood": "analytical",
                "execution_policy": "docs_research",
                "workflow_phase": "planning",
            },
            "provider": "anthropic",
            "model": "claude-3-opus",
            "routing_reason": "research task",
            "candidate_count": 1,
        }

        v2_data = SchemaEvolutionService.migrate(v1_data, "1.0", "2.0", "RoutingDecision")

        # Should use summary if resolved_profile not available
        profile = v2_data["profile"]
        assert profile["agent_preset"] == "researcher"
        assert profile["mood"] == "analytical"

        binding = v2_data["binding"]
        assert binding["provider"] == "anthropic"
        assert binding["model"] == "claude-3-opus"

    def test_migrate_routing_decision_1_to_2_with_defaults(self):
        """Migrate RoutingDecision v1.0 with missing fields uses defaults."""
        v1_data = {
            "provider": "local_ollama",
            "model": "llama3",
        }

        v2_data = SchemaEvolutionService.migrate(v1_data, "1.0", "2.0", "RoutingDecision")

        # Defaults applied
        profile = v2_data["profile"]
        assert profile["agent_preset"] == "executor"
        assert profile["task_role"] == "executor"
        assert profile["mood"] == "neutral"
        assert profile["execution_policy"] == "workspace_safe"
        assert profile["workflow_phase"] == "executing"

        binding = v2_data["binding"]
        assert binding["provider"] == "local_ollama"
        assert binding["model"] == "llama3"

    def test_migrate_plan_node_1_to_2(self):
        """Migrate PlanNode v1.0 → v2.0."""
        v1_data = {
            "id": "node-1",
            "label": "Test Node",
            "prompt": "Do something",
            "model": "gpt-4",
            "provider": "openai",
            "agent_preset": "executor",
            "task_role": "executor",
            "mood": "neutral",
            "execution_policy": "workspace_safe",
            "workflow_phase": "executing",
            "binding_mode": "plan_time",
            "role": "executor",
            "node_type": "action",
            "status": "pending",
        }

        v2_data = SchemaEvolutionService.migrate(v1_data, "1.0", "2.0", "PlanNode")

        # Verify v2 structure
        assert v2_data["schema_version"] == "2.0"
        assert "routing_decision" in v2_data

        # Verify routing_decision created
        routing = v2_data["routing_decision"]
        assert routing["schema_version"] == "2.0"
        assert "profile" in routing
        assert "binding" in routing

        # Verify profile
        profile = routing["profile"]
        assert profile["agent_preset"] == "executor"
        assert profile["execution_policy"] == "workspace_safe"

        # Verify binding
        binding = routing["binding"]
        assert binding["provider"] == "openai"
        assert binding["model"] == "gpt-4"

        # Verify core fields preserved
        assert v2_data["id"] == "node-1"
        assert v2_data["label"] == "Test Node"
        assert v2_data["prompt"] == "Do something"
        assert v2_data["role"] == "executor"
        assert v2_data["status"] == "pending"

    def test_migrate_plan_node_1_to_2_with_resolved_profile(self):
        """Migrate PlanNode v1.0 with existing resolved_profile."""
        v1_data = {
            "id": "node-2",
            "label": "Node with profile",
            "resolved_profile": {
                "agent_preset": "reviewer",
                "task_role": "reviewer",
                "mood": "cautious",
                "execution_policy": "read_only",
                "workflow_phase": "reviewing",
            },
            "model": "claude-3-sonnet",
            "provider": "claude-account",
        }

        v2_data = SchemaEvolutionService.migrate(v1_data, "1.0", "2.0", "PlanNode")

        # Should use existing resolved_profile
        routing = v2_data["routing_decision"]
        profile = routing["profile"]
        assert profile["agent_preset"] == "reviewer"
        assert profile["task_role"] == "reviewer"
        assert profile["mood"] == "cautious"

    def test_migrate_plan_node_1_to_2_with_binding_object(self):
        """Migrate PlanNode v1.0 with binding object."""
        v1_data = {
            "id": "node-3",
            "binding": {
                "provider": "openai",
                "model": "gpt-4-turbo",
                "binding_mode": "runtime",
            },
        }

        v2_data = SchemaEvolutionService.migrate(v1_data, "1.0", "2.0", "PlanNode")

        # Should use binding object if available
        routing = v2_data["routing_decision"]
        binding = routing["binding"]
        assert binding["provider"] == "openai"
        assert binding["model"] == "gpt-4-turbo"
        assert binding["binding_mode"] == "runtime"

    def test_migrate_same_version_no_op(self):
        """Migrating same version returns data unchanged."""
        data = {"test": "data"}
        result = SchemaEvolutionService.migrate(data, "2.0", "2.0", "RoutingDecision")
        assert result == data

    def test_migrate_unknown_path_raises_error(self):
        """Migrating with no defined path raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            SchemaEvolutionService.migrate({}, "2.0", "3.0", "RoutingDecision")

        assert "No migration path" in str(exc_info.value)

    def test_migrate_unknown_schema_raises_error(self):
        """Migrating unknown schema raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            SchemaEvolutionService.migrate({}, "1.0", "2.0", "UnknownSchema")

        assert "No migration path" in str(exc_info.value)

    def test_get_breaking_changes_routing_decision(self):
        """get_breaking_changes returns empty list for backward compatible migration."""
        changes = SchemaEvolutionService.get_breaking_changes("RoutingDecision", "1.0", "2.0")
        assert isinstance(changes, list)
        assert len(changes) == 0  # v2.0 is backward compatible

    def test_get_breaking_changes_unknown_schema(self):
        """get_breaking_changes returns empty list for unknown schema."""
        changes = SchemaEvolutionService.get_breaking_changes("UnknownSchema", "1.0", "2.0")
        assert isinstance(changes, list)
        assert len(changes) == 0

    def test_get_version_info_routing_decision(self):
        """get_version_info returns schema metadata."""
        info = SchemaEvolutionService.get_version_info("RoutingDecision", "2.0")

        assert "fields" in info
        assert "description" in info
        assert "backward_compatible" in info
        assert info["backward_compatible"] is True

        # Check fields list
        fields = info["fields"]
        assert "profile" in fields
        assert "binding" in fields
        assert "routing_reason" in fields

    def test_get_version_info_v1(self):
        """get_version_info returns v1.0 metadata."""
        info = SchemaEvolutionService.get_version_info("RoutingDecision", "1.0")

        assert "fields" in info
        assert "description" in info

        # v1.0 fields
        fields = info["fields"]
        assert "summary" in fields
        assert "resolved_profile" in fields
        assert "provider" in fields

    def test_get_version_info_unknown_version(self):
        """get_version_info returns empty dict for unknown version."""
        info = SchemaEvolutionService.get_version_info("RoutingDecision", "9.9")
        assert info == {}

    def test_schema_versions_registry_structure(self):
        """SCHEMA_VERSIONS has correct structure."""
        registry = SchemaEvolutionService.SCHEMA_VERSIONS

        assert "RoutingDecision" in registry
        assert "PlanNode" in registry

        # Check RoutingDecision versions
        rd_versions = registry["RoutingDecision"]
        assert "1.0" in rd_versions
        assert "2.0" in rd_versions

        # Check v2.0 metadata
        v2 = rd_versions["2.0"]
        assert "fields" in v2
        assert "description" in v2
        assert "backward_compatible" in v2
        assert v2["backward_compatible"] is True
