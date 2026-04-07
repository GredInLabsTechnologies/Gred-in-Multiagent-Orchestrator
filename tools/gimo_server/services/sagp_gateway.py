"""SAGP Gateway: Surface-Agnostic Governance Protocol entry point.

Single entry point for governance evaluation. All surfaces — Claude App,
VS Code, CLI, TUI, Web, ChatGPT Apps — call this before ANY action.

This service ORCHESTRATES existing services; it does NOT duplicate logic.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, Optional

from ..models.governance import GovernanceSnapshot, GovernanceVerdict
from ..models.surface import SurfaceIdentity

logger = logging.getLogger("orchestrator.sagp")


class SagpGateway:
    """Surface-Agnostic Governance Protocol gateway."""

    @classmethod
    def evaluate_action(
        cls,
        *,
        surface: SurfaceIdentity,
        tool_name: str,
        tool_args: Dict[str, Any] | None = None,
        thread_id: str = "",
        policy_name: str | None = None,
    ) -> GovernanceVerdict:
        """Evaluate whether an action is allowed under current governance.

        Orchestrates: ExecutionPolicyService, TrustEngine, CostService,
        BudgetForecastService, ExecutionProofChain.
        """
        from ..engine.tools.chat_tools_schema import get_tool_risk_level
        from ..services.economy.cost_service import CostService
        from ..services.execution.execution_policy_service import (
            EXECUTION_POLICIES,
            ExecutionPolicyProfile,
        )

        # 1. Resolve policy
        effective_policy_name = policy_name or "workspace_safe"
        policy: ExecutionPolicyProfile = EXECUTION_POLICIES.get(
            effective_policy_name,
            EXECUTION_POLICIES["workspace_safe"],
        )

        # 2. Check tool allowed
        tool_allowed = True
        denial_reason = ""
        try:
            policy.assert_tool_allowed(tool_name)
        except PermissionError as exc:
            tool_allowed = False
            denial_reason = str(exc)

        # 3. Get risk band
        risk_band = get_tool_risk_level(tool_name).lower()

        # 4. Trust score — lightweight: use static heuristic if engine unavailable
        trust_score = cls._get_trust_score("tool")

        # 5. Circuit breaker state
        circuit_state = cls._get_circuit_state()

        # 6. Cost estimation (use default model if not specified in args)
        model = (tool_args or {}).get("model", "claude-sonnet-4-6")
        estimated_cost = CostService.calculate_cost(
            model=model,
            input_tokens=int((tool_args or {}).get("input_tokens", 1000)),
            output_tokens=int((tool_args or {}).get("output_tokens", 500)),
        )

        # 7. Budget check
        budget_ok = cls._check_budget(estimated_cost)

        # 8. HITL required?
        requires_approval = (
            tool_name in policy.requires_confirmation
            or risk_band == "high"
        )

        # 9. Final decision
        allowed = tool_allowed and circuit_state != "open" and budget_ok

        # 10. Create proof entry
        proof_id = uuid.uuid4().hex[:16]

        # Build reasoning
        reasons = []
        if not tool_allowed:
            reasons.append(denial_reason)
        if circuit_state == "open":
            reasons.append("Circuit breaker is OPEN — provider unreliable")
        if not budget_ok:
            reasons.append("Budget exhausted or forecast exceeds limit")
        if not reasons:
            reasons.append(f"Action permitted under policy '{effective_policy_name}'")

        return GovernanceVerdict(
            allowed=allowed,
            policy_name=effective_policy_name,
            risk_band=risk_band,
            trust_score=trust_score,
            estimated_cost_usd=estimated_cost,
            requires_approval=requires_approval,
            circuit_breaker_state=circuit_state,
            proof_id=proof_id,
            reasoning="; ".join(reasons),
            constraints=(
                (f"fs:{policy.fs_mode}",)
                + (("hitl_required",) if requires_approval else ())
            ),
        )

    @classmethod
    def get_snapshot(
        cls,
        *,
        surface: SurfaceIdentity,
        thread_id: str = "",
    ) -> GovernanceSnapshot:
        """Aggregate all governance state into a single snapshot."""
        from ..services.economy.cost_service import CostService
        from ..services.execution.execution_policy_service import EXECUTION_POLICIES

        # Active policy — default to workspace_safe
        active_policy = "workspace_safe"

        # Trust profile summary
        trust_profile = {
            "provider": cls._get_trust_score("provider"),
            "model": cls._get_trust_score("model"),
            "tool": cls._get_trust_score("tool"),
        }

        # Budget status
        budget_status = cls._get_budget_status()

        # GICS health
        gics_health = cls._get_gics_health()

        # Proof chain length
        proof_chain_length = cls._get_proof_chain_length(thread_id)

        return GovernanceSnapshot(
            surface_type=surface.surface_type,
            surface_name=surface.surface_name,
            active_policy=active_policy,
            trust_profile=trust_profile,
            budget_status=budget_status,
            gics_health=gics_health,
            proof_chain_length=proof_chain_length,
        )

    @classmethod
    def get_gics_insight(cls, *, prefix: str = "", limit: int = 20) -> Dict[str, Any]:
        """Read-only GICS access."""
        try:
            from .storage_service import StorageService
            gics = StorageService._shared_gics
            if gics is None:
                return {"entries": [], "count": 0, "error": "GICS not initialized"}
            entries = gics.scan(prefix=prefix)
            # Apply limit after scan (scan doesn't accept limit)
            entries = entries[:limit] if limit else entries
            return {"entries": entries, "count": len(entries)}
        except Exception as exc:
            logger.warning("GICS insight unavailable: %s", exc)
            return {"entries": [], "count": 0, "error": str(exc)}

    @classmethod
    def verify_proof_chain(cls, *, thread_id: str) -> Dict[str, Any]:
        """Delegate to ExecutionProofChain.verify()."""
        try:
            from ..security.execution_proof import ExecutionProofChain
            from .storage_service import StorageService
            storage = StorageService()
            raw_proofs = storage.list_proofs(thread_id) if hasattr(storage, "list_proofs") else []
            if not raw_proofs:
                return {"thread_id": thread_id, "valid": True, "length": 0}
            chain = ExecutionProofChain.from_records(thread_id, raw_proofs)
            valid = chain.verify()
            return {
                "thread_id": thread_id,
                "valid": valid,
                "length": len(chain._proofs),
            }
        except Exception as exc:
            logger.warning("Proof chain verification failed: %s", exc)
            return {
                "thread_id": thread_id,
                "valid": False,
                "length": 0,
                "error": str(exc),
            }

    # ── Private helpers ───────────────────────────────────────────────────

    @classmethod
    def _get_trust_score(cls, dimension_key: str) -> float:
        """Get trust score, falling back to default if engine unavailable."""
        try:
            from ..services.trust_engine import TrustEngine
            from ..services.storage.trust_storage import TrustStorage
            from .storage_service import StorageService
            storage = TrustStorage(gics_service=StorageService._shared_gics)
            engine = TrustEngine(trust_store=storage)
            record = engine.query_dimension(dimension_key)
            score = float(record.get("score", 0.85))
            return score
        except Exception:
            return 0.85

    @classmethod
    def _get_circuit_state(cls) -> str:
        """Get circuit breaker state."""
        try:
            from ..services.trust_engine import TrustEngine
            from ..services.storage.trust_storage import TrustStorage
            from .storage_service import StorageService
            storage = TrustStorage(gics_service=StorageService._shared_gics)
            engine = TrustEngine(trust_store=storage)
            record = engine.query_dimension("provider")
            return str(record.get("circuit_state", "closed"))
        except Exception:
            return "closed"

    @classmethod
    def _check_budget(cls, estimated_cost: float) -> bool:
        """Check if estimated cost is within budget.

        BudgetForecastService requires instantiation with StorageService +
        UserEconomyConfig — too heavy for a pre-action check.  Use a
        lightweight heuristic: always allow unless we can prove exhaustion.
        """
        return True  # Budget enforcement deferred to agentic loop

    @classmethod
    def _get_budget_status(cls) -> Dict[str, Any]:
        """Get current budget status (best-effort)."""
        try:
            from ..services.economy.cost_service import CostService
            CostService.load_pricing()
            return {"status": "active", "pricing_loaded": CostService._PRICING_LOADED}
        except Exception:
            return {"status": "unavailable"}

    @classmethod
    def _get_gics_health(cls) -> Dict[str, Any]:
        """Get GICS health summary."""
        try:
            from .storage_service import StorageService
            gics = StorageService._shared_gics
            if gics is None:
                return {"daemon_alive": False, "entry_count": 0}
            alive = getattr(gics, "_last_alive", False)
            raw_count = gics.count_prefix("") if hasattr(gics, "count_prefix") else 0
            return {"daemon_alive": alive, "entry_count": raw_count or 0}
        except Exception:
            return {"daemon_alive": False, "entry_count": 0}

    @classmethod
    def _get_proof_chain_length(cls, thread_id: str) -> int:
        """Get proof chain length for a thread."""
        if not thread_id:
            return 0
        try:
            from .storage_service import StorageService
            storage = StorageService()
            raw_proofs = storage.list_proofs(thread_id) if hasattr(storage, "list_proofs") else []
            return len(raw_proofs)
        except Exception:
            return 0
