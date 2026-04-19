"""PlanMigrationService — Migrates legacy PlanNode data to canonical v2.0 routing_decision.

Handles backward compatibility for nodes created before the v2.0 contract refactor.
"""
from __future__ import annotations

import json
import logging
from typing import Dict, Any, List

from ..models.plan import PlanNode
from ..models.agent_routing import RoutingDecision, ModelBinding, ResolvedAgentProfile

logger = logging.getLogger("orchestrator.plan_migration")


class PlanMigrationService:
    """Handles migration from legacy PlanNode structure (v1.0) to canonical v2.0."""

    @classmethod
    def migrate_node(cls, node: PlanNode) -> PlanNode:
        """Migrate legacy node to canonical v2.0 structure.

        Args:
            node: PlanNode potentially with legacy v1.0 fields

        Returns:
            PlanNode with routing_decision populated (v2.0)

        Notes:
            - If routing_decision exists, returns unchanged
            - Otherwise builds routing_decision from legacy fields
            - Idempotent: safe to call multiple times
        """
        if node.routing_decision:
            # Already v2.0, nothing to do
            return node

        # Extract legacy fields directly from node attributes
        # Build ModelBinding from legacy fields
        binding = ModelBinding(
            provider=node.provider or "auto",
            model=node.model or "auto",
            binding_mode=node.binding_mode or "plan_time",
            binding_reason="migrated_from_legacy_v1"
        )

        # Build ResolvedAgentProfile from legacy fields
        if node.resolved_profile:
            # Use existing resolved_profile if available
            profile = node.resolved_profile
        else:
            # Reconstruct from scattered fields
            profile = ResolvedAgentProfile(
                agent_preset=node.agent_preset or "executor",
                task_role="executor",  # Not stored separately in legacy
                mood="neutral",  # Not stored separately in legacy
                execution_policy=node.execution_policy or "workspace_safe",
                workflow_phase=node.workflow_phase or "executing",
            )

        # Build canonical RoutingDecision
        routing_decision = RoutingDecision(
            profile=profile,
            binding=binding,
            routing_reason=node.routing_reason or "migrated_from_legacy_v1",
            candidate_count=1,  # Unknown for legacy nodes
        )

        # Update node with canonical routing_decision
        node.routing_decision = routing_decision

        logger.info(
            "Migrated node %s from v1.0 to v2.0: preset=%s, provider=%s/%s",
            node.id,
            profile.agent_preset,
            binding.provider,
            binding.model,
        )

        return node

    @classmethod
    def migrate_nodes(cls, nodes: list[PlanNode]) -> list[PlanNode]:
        """Migrate multiple nodes in batch.

        Args:
            nodes: List of PlanNodes to migrate

        Returns:
            List of migrated PlanNodes (v2.0)
        """
        migrated = []
        for node in nodes:
            try:
                migrated.append(cls.migrate_node(node))
            except Exception as e:
                logger.error("Failed to migrate node %s: %s", node.id, e)
                # Keep original node on error
                migrated.append(node)
        return migrated

    @classmethod
    def needs_migration(cls, node: PlanNode) -> bool:
        """Check if a node needs migration to v2.0.

        Args:
            node: PlanNode to check

        Returns:
            True if node needs migration (no routing_decision)
        """
        return node.routing_decision is None

    @classmethod
    def analyze_legacy_fields(cls, node: PlanNode) -> Dict[str, Any]:
        """Analyze legacy fields in a node for debugging.

        Args:
            node: PlanNode to analyze

        Returns:
            Dict with analysis results
        """
        # Check legacy fields directly from node attributes
        legacy_fields = {
            "model": node.model,
            "provider": node.provider,
            "agent_preset": node.agent_preset,
            "execution_policy": node.execution_policy,
            "binding_mode": node.binding_mode,
            "workflow_phase": node.workflow_phase,
            "resolved_profile": node.resolved_profile,
            "routing_decision_summary": node.routing_decision_summary,
        }

        # Filter out None values
        found = {k: v for k, v in legacy_fields.items() if v is not None}

        return {
            "node_id": node.id,
            "has_routing_decision": node.routing_decision is not None,
            "schema_version": node.schema_version,
            "legacy_fields_found": list(found.keys()),
            "legacy_values": found,
            "needs_migration": cls.needs_migration(node),
        }

    @classmethod
    def audit_migration_status(cls) -> Dict[str, Any]:
        """Read raw JSON plans without triggering migration and count v1 vs v2 nodes."""
        from ..config import OPS_DATA_DIR

        plans_dir = OPS_DATA_DIR / "custom_plans"
        if not plans_dir.exists():
            return {
                "total_plans": 0,
                "total_nodes": 0,
                "v1_nodes": 0,
                "v2_nodes": 0,
                "migration_complete": True,
                "plans_with_legacy": [],
            }

        total_plans = 0
        total_nodes = 0
        v1_nodes = 0
        v2_nodes = 0
        plans_with_legacy: List[str] = []

        for f in plans_dir.glob("*.json"):
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            total_plans += 1
            nodes = raw.get("nodes") or []
            has_legacy = False
            for node in nodes:
                total_nodes += 1
                if node.get("routing_decision"):
                    v2_nodes += 1
                else:
                    v1_nodes += 1
                    has_legacy = True
            if has_legacy:
                plans_with_legacy.append(raw.get("id", f.stem))

        return {
            "total_plans": total_plans,
            "total_nodes": total_nodes,
            "v1_nodes": v1_nodes,
            "v2_nodes": v2_nodes,
            "migration_complete": v1_nodes == 0,
            "plans_with_legacy": plans_with_legacy,
        }

    @classmethod
    def audit_run_routing_coverage(cls) -> Dict[str, Any]:
        """Count runs with/without routing metadata (agent_preset)."""
        from ..config import OPS_DATA_DIR

        runs_dir = OPS_DATA_DIR / "runs"
        if not runs_dir.exists():
            return {
                "total_runs": 0,
                "with_routing_metadata": 0,
                "without_routing_metadata": 0,
                "coverage_pct": 100.0,
            }

        total_runs = 0
        with_routing = 0

        for f in runs_dir.glob("*.json"):
            try:
                raw = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            total_runs += 1
            if raw.get("agent_preset"):
                with_routing += 1

        without_routing = total_runs - with_routing
        coverage_pct = (with_routing / total_runs * 100.0) if total_runs > 0 else 100.0

        return {
            "total_runs": total_runs,
            "with_routing_metadata": with_routing,
            "without_routing_metadata": without_routing,
            "coverage_pct": round(coverage_pct, 1),
        }
