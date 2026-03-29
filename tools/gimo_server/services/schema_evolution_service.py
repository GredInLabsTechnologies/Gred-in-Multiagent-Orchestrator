"""SchemaEvolutionService — Handles schema migrations with backward compatibility.

Manages schema versioning and provides migration paths between versions.
"""
from __future__ import annotations

import logging
from typing import Dict, Any, List

logger = logging.getLogger("orchestrator.schema_evolution")


class SchemaEvolutionService:
    """Manages schema evolution with backward compatibility."""

    # Schema version registry
    SCHEMA_VERSIONS = {
        "RoutingDecision": {
            "1.0": {
                "fields": ["summary", "resolved_profile", "provider", "model", "binding_mode",
                          "routing_reason", "candidate_count", "routing_schema_version", "profile_schema_version"],
                "description": "Original schema with redundant fields",
            },
            "2.0": {
                "fields": ["profile", "binding", "routing_reason", "candidate_count", "schema_version"],
                "description": "Consolidated schema with single source of truth",
                "backward_compatible": True,
                "breaking_changes": [],
            },
        },
        "PlanNode": {
            "1.0": {
                "fields": ["id", "label", "prompt", "model", "provider", "role", "node_type",
                          "agent_preset", "binding_mode", "execution_policy", "workflow_phase",
                          "resolved_profile", "routing_decision_summary", "binding", "routing_reason"],
                "description": "Original schema with scattered routing data",
            },
            "2.0": {
                "fields": ["id", "label", "prompt", "role", "node_type", "routing_decision",
                          "task_fingerprint", "task_descriptor", "status", "output", "error",
                          "position", "config", "schema_version"],
                "description": "Consolidated schema with routing_decision as single source",
                "backward_compatible": True,
                "breaking_changes": [],
            },
        },
    }

    @classmethod
    def get_current_version(cls, schema_name: str) -> str:
        """Get current schema version for a contract.

        Args:
            schema_name: Name of schema (e.g., "RoutingDecision")

        Returns:
            Current version string (e.g., "2.0")
        """
        versions = cls.SCHEMA_VERSIONS.get(schema_name, {})
        if not versions:
            return "1.0"
        # Return highest version
        return max(versions.keys(), key=lambda v: [int(x) for x in v.split(".")])

    @classmethod
    def is_compatible(cls, schema_name: str, from_version: str, to_version: str) -> bool:
        """Check if migration from_version -> to_version is backward compatible.

        Args:
            schema_name: Name of schema
            from_version: Source version
            to_version: Target version

        Returns:
            True if backward compatible
        """
        versions = cls.SCHEMA_VERSIONS.get(schema_name, {})
        target = versions.get(to_version, {})
        return target.get("backward_compatible", False)

    @classmethod
    def migrate(cls, data: Dict, from_version: str, to_version: str, schema_name: str) -> Dict:
        """Migrate data from one version to another.

        Args:
            data: Data dict to migrate
            from_version: Source version
            to_version: Target version
            schema_name: Name of schema

        Returns:
            Migrated data dict

        Raises:
            ValueError: If no migration path exists
        """
        if from_version == to_version:
            return data

        if schema_name == "RoutingDecision":
            if from_version == "1.0" and to_version == "2.0":
                return cls._migrate_routing_decision_1_to_2(data)
        elif schema_name == "PlanNode":
            if from_version == "1.0" and to_version == "2.0":
                return cls._migrate_plan_node_1_to_2(data)

        raise ValueError(f"No migration path: {schema_name} {from_version} → {to_version}")

    @classmethod
    def _migrate_routing_decision_1_to_2(cls, data: Dict) -> Dict:
        """Migrate RoutingDecision v1 → v2.

        v1: summary, resolved_profile, provider, model, binding_mode, routing_reason, candidate_count
        v2: profile, binding, routing_reason, candidate_count, schema_version
        """
        # Extract profile from resolved_profile or summary
        profile_data = data.get("resolved_profile") or data.get("summary", {})
        if isinstance(profile_data, dict):
            profile = {
                "agent_preset": profile_data.get("agent_preset", "executor"),
                "task_role": profile_data.get("task_role", "executor"),
                "mood": profile_data.get("mood", "neutral"),
                "execution_policy": profile_data.get("execution_policy", "workspace_safe"),
                "workflow_phase": profile_data.get("workflow_phase", "executing"),
            }
        else:
            # Fallback if profile_data is not dict
            profile = {
                "agent_preset": "executor",
                "task_role": "executor",
                "mood": "neutral",
                "execution_policy": "workspace_safe",
                "workflow_phase": "executing",
            }

        # Extract binding
        binding = {
            "provider": data.get("provider", "auto"),
            "model": data.get("model", "auto"),
            "binding_mode": data.get("binding_mode", "plan_time"),
            "binding_reason": "migrated_from_v1",
        }

        migrated = {
            "profile": profile,
            "binding": binding,
            "routing_reason": data.get("routing_reason", "migrated_from_v1"),
            "candidate_count": data.get("candidate_count", 1),
            "schema_version": "2.0",
        }

        logger.debug(
            "Migrated RoutingDecision v1→v2: preset=%s, provider=%s",
            profile["agent_preset"],
            binding["provider"]
        )

        return migrated

    @classmethod
    def _migrate_plan_node_1_to_2(cls, data: Dict) -> Dict:
        """Migrate PlanNode v1 → v2.

        v1: scattered routing fields (model, provider, agent_preset, resolved_profile, etc.)
        v2: routing_decision as single source of truth
        """
        # Build routing_decision from v1 fields
        resolved_profile = data.get("resolved_profile")
        if resolved_profile:
            profile = resolved_profile
        else:
            profile = {
                "agent_preset": data.get("agent_preset", "executor"),
                "task_role": data.get("task_role", "executor"),
                "mood": data.get("mood", "neutral"),
                "execution_policy": data.get("execution_policy", "workspace_safe"),
                "workflow_phase": data.get("workflow_phase", "executing"),
            }

        binding_obj = data.get("binding")
        if binding_obj and isinstance(binding_obj, dict):
            binding = {
                "provider": binding_obj.get("provider", "auto"),
                "model": binding_obj.get("model", "auto"),
                "binding_mode": binding_obj.get("binding_mode", "plan_time"),
                "binding_reason": "migrated_from_v1",
            }
        else:
            binding = {
                "provider": data.get("provider", "auto"),
                "model": data.get("model", "auto"),
                "binding_mode": data.get("binding_mode", "plan_time"),
                "binding_reason": "migrated_from_v1",
            }

        routing_decision = {
            "profile": profile,
            "binding": binding,
            "routing_reason": data.get("routing_reason", "migrated_from_v1"),
            "candidate_count": 1,
            "schema_version": "2.0",
        }

        # Build v2 PlanNode
        migrated = {
            "id": data["id"],
            "label": data.get("label", ""),
            "prompt": data.get("prompt", ""),
            "role": data.get("role", "worker"),
            "node_type": data.get("node_type", "worker"),
            "role_definition": data.get("role_definition", ""),
            "is_orchestrator": data.get("is_orchestrator", False),
            "depends_on": data.get("depends_on", []),
            "routing_decision": routing_decision,
            "task_fingerprint": data.get("task_fingerprint"),
            "task_descriptor": data.get("task_descriptor"),
            "status": data.get("status", "pending"),
            "output": data.get("output"),
            "error": data.get("error"),
            "position": data.get("position", {"x": 0, "y": 0}),
            "config": data.get("config", {}),
            "schema_version": "2.0",
        }

        logger.debug(
            "Migrated PlanNode v1→v2: id=%s, preset=%s",
            migrated["id"],
            profile["agent_preset"]
        )

        return migrated

    @classmethod
    def get_breaking_changes(cls, schema_name: str, from_version: str, to_version: str) -> List[str]:
        """Get list of breaking changes between versions.

        Args:
            schema_name: Name of schema
            from_version: Source version
            to_version: Target version

        Returns:
            List of breaking change descriptions
        """
        versions = cls.SCHEMA_VERSIONS.get(schema_name, {})
        target = versions.get(to_version, {})
        return target.get("breaking_changes", [])

    @classmethod
    def get_version_info(cls, schema_name: str, version: str) -> Dict[str, Any]:
        """Get detailed information about a schema version.

        Args:
            schema_name: Name of schema
            version: Version string

        Returns:
            Dict with version info (fields, description, compatibility)
        """
        versions = cls.SCHEMA_VERSIONS.get(schema_name, {})
        return versions.get(version, {})
