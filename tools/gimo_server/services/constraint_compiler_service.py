from __future__ import annotations

import logging
from typing import Any, Dict

from ..models.agent_routing import TaskConstraints, TaskDescriptor
from .intent_classification_service import IntentClassificationService
from .provider_service import ProviderService
from .provider_topology_service import ProviderTopologyService
from .runtime_policy_service import RuntimePolicyService
from .workspace_policy_service import WorkspacePolicyService

logger = logging.getLogger("orchestrator.services.constraint_compiler")


class ConstraintCompilerService:
    _BASE_POLICIES_BY_SEMANTIC: Dict[str, list[str]] = {
        "planning": ["propose_only", "read_only"],
        "research": ["docs_research", "read_only"],
        "security": ["security_audit", "read_only"],
        "review": ["read_only", "security_audit"],
        "approval": ["propose_only"],
        "implementation": ["workspace_safe", "workspace_experiment"],
    }
    _RUNTIME_ROLE_ALLOWLIST = frozenset({"worker", "executor", "reviewer", "researcher", "human_gate"})
    _RUNTIME_TOPOLOGY_HINTS = frozenset({"dynamic", "runtime", "adaptive"})
    _RISK_SCORE_BY_BAND = {
        "low": 10.0,
        "medium": 20.0,
        "high": 55.0,
    }

    @classmethod
    def _base_policies(cls, descriptor: TaskDescriptor) -> list[str]:
        return list(
            cls._BASE_POLICIES_BY_SEMANTIC.get(
                descriptor.task_semantic,
                cls._BASE_POLICIES_BY_SEMANTIC["implementation"],
            )
        )

    @classmethod
    def _safe_int(cls, value: Any) -> int | None:
        try:
            if value is None:
                return None
            out = int(value)
            return max(out, 0)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _safe_float(cls, value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @classmethod
    def _resolve_surface_context(cls, task_context: Dict[str, Any]) -> tuple[str, str, list[str]]:
        notes: list[str] = []
        surface = str(task_context.get("surface") or WorkspacePolicyService.SURFACE_OPERATOR).strip().lower()
        if not surface:
            surface = WorkspacePolicyService.SURFACE_OPERATOR
        requested_mode = task_context.get("workspace_mode")
        try:
            workspace_mode = WorkspacePolicyService.resolve_effective_mode(
                requested_mode=requested_mode,
                surface=surface,
            )
        except ValueError:
            workspace_mode = str(requested_mode or "").strip().lower() or WorkspacePolicyService.MODE_EPHEMERAL
            notes.append("workspace_mode_rejected_for_surface")
            return surface, workspace_mode, notes
        return surface, workspace_mode, notes

    @classmethod
    def _derive_risk_score(cls, descriptor: TaskDescriptor, task_context: Dict[str, Any]) -> float:
        explicit = cls._safe_float(task_context.get("risk_score"))
        if explicit is not None:
            return max(explicit, 0.0)
        risk = cls._RISK_SCORE_BY_BAND.get(str(descriptor.risk_band or "").strip().lower(), 20.0)
        if descriptor.mutation_mode == "none":
            return min(risk, 20.0)
        return risk

    @classmethod
    def _apply_budget_envelope(
        cls,
        *,
        allowed_policies: list[str],
        task_context: Dict[str, Any],
        compiler_notes: list[str],
    ) -> tuple[list[str], str]:
        budget_mode = str(task_context.get("budget_mode") or "").strip().lower() or "standard"
        budget_usd = cls._safe_float(task_context.get("budget_usd"))

        narrowed = list(allowed_policies)
        if budget_mode in {"zero", "blocked"} or (budget_usd is not None and budget_usd <= 0):
            compiler_notes.append("budget_exhausted")
            return [], "blocked"
        if budget_mode in {"tight", "low"} or (budget_usd is not None and budget_usd < 1.0):
            narrowed = [policy for policy in narrowed if policy != "workspace_experiment"]
            compiler_notes.append("budget_clamped_experimental_policy")
            return narrowed, "tight"
        return narrowed, budget_mode

    @classmethod
    def _compile_binding_modes(
        cls,
        descriptor: TaskDescriptor,
        task_context: Dict[str, Any],
        *,
        requires_human_approval: bool,
        compiler_notes: list[str],
    ) -> list[str]:
        requested_binding_mode = str(task_context.get("binding_mode") or "").strip().lower()
        requested_role = str(task_context.get("requested_role") or "").strip().lower()
        has_dependencies = bool(task_context.get("depends_on"))
        topology_mode = str(task_context.get("topology_mode") or "").strip().lower()
        runtime_justified = has_dependencies or requires_human_approval or topology_mode in cls._RUNTIME_TOPOLOGY_HINTS
        runtime_role_allowed = requested_role in cls._RUNTIME_ROLE_ALLOWLIST or (
            not requested_role and descriptor.task_semantic != "planning"
        )

        if requested_binding_mode == "runtime":
            if runtime_justified and runtime_role_allowed:
                compiler_notes.append("runtime_binding_allowed")
                return ["runtime", "plan_time"]
            compiler_notes.append("runtime_binding_rejected_by_allowlist")
        elif runtime_justified and runtime_role_allowed and topology_mode in cls._RUNTIME_TOPOLOGY_HINTS:
            compiler_notes.append("runtime_binding_allowed_for_dynamic_topology")
            return ["plan_time", "runtime"]

        return ["plan_time"]

    @classmethod
    def _is_gics_daemon_available(cls) -> bool:
        """Fast non-blocking check: is the GICS daemon socket/pipe reachable?"""
        import os, sys
        if sys.platform == "win32":
            return os.path.exists(r"\\.\pipe\gics-daemon")
        # Unix: check socket file
        gics_home = os.path.join(os.path.expanduser("~"), ".gics")
        return os.path.exists(os.path.join(gics_home, "gics.sock"))

    @classmethod
    def apply_trust_authority(
        cls,
        execution_policy: str,
        *,
        model_id: str | None = None,
        provider_type: str | None = None,
        workspace_root: str | None = None,
    ) -> tuple[str, bool]:
        """Dynamically constrain execution policy based on trust and reliability signals.

        Returns (effective_policy, requires_human_approval).
        Fail-open: if signals unavailable, returns policy unchanged.
        """
        requires_approval = False

        # Check GICS model reliability — anomalous model loses write authority
        if model_id and provider_type and cls._is_gics_daemon_available():
            try:
                from .gics_service import GicsService
                gics = GicsService()
                reliability = gics.get_model_reliability(
                    provider_type=provider_type, model_id=model_id,
                )
                if reliability and reliability.get("anomaly"):
                    logger.info(
                        "Trust authority: model %s/%s anomaly detected, clamping to propose_only",
                        provider_type, model_id,
                    )
                    return "propose_only", False
            except Exception:
                pass  # Fail-open

        # Check TrustEngine workspace dimension
        if workspace_root and cls._is_gics_daemon_available():
            try:
                from .storage_service import StorageService
                from .trust_engine import TrustEngine
                storage = StorageService()
                engine = TrustEngine(storage.trust)
                trust_record = engine.query_dimension(f"workspace:{workspace_root}")
                trust_policy = trust_record.get("policy")
                # No policy key = no trust data yet → fail-open (auto_approve)
                if trust_policy is None:
                    pass  # New workspace, no data — full authority
                elif trust_policy == "blocked":
                    logger.info(
                        "Trust authority: workspace %s blocked, clamping to propose_only",
                        workspace_root,
                    )
                    return "propose_only", False
                elif trust_policy == "require_review":
                    requires_approval = True
            except Exception:
                pass  # Fail-open

        return execution_policy, requires_approval

    @classmethod
    def compile_for_descriptor(
        cls,
        descriptor: TaskDescriptor,
        task_context: Dict[str, Any] | None = None,
    ) -> TaskConstraints:
        context = dict(task_context or {})
        compiler_notes: list[str] = []
        allowed_policies = cls._base_policies(descriptor)
        surface, workspace_mode, surface_notes = cls._resolve_surface_context(context)
        compiler_notes.extend(surface_notes)
        if "workspace_mode_rejected_for_surface" in compiler_notes:
            return TaskConstraints(
                allowed_policies=[],
                allowed_binding_modes=["plan_time"],
                requires_human_approval=False,
                surface=surface,
                workspace_mode=workspace_mode,
                policy_decision="deny",
                policy_status_code="WORKSPACE_MODE_NOT_ALLOWED",
                budget_mode="blocked",
                compiler_notes=compiler_notes,
            )

        if descriptor.mutation_mode == "workspace" and not WorkspacePolicyService.allows_experimental_policy(workspace_mode):
            allowed_policies = [policy for policy in allowed_policies if policy != "workspace_experiment"]
            compiler_notes.append("workspace_experiment_disallowed_for_workspace_mode")

        allowed_policies, budget_mode = cls._apply_budget_envelope(
            allowed_policies=allowed_policies,
            task_context=context,
            compiler_notes=compiler_notes,
        )

        requires_human_approval = descriptor.task_semantic == "approval" or bool(context.get("requires_human_approval"))
        policy_decision = "allow"
        policy_status_code = "POLICY_ALLOW"

        estimated_files_changed, estimated_loc_changed = RuntimePolicyService.estimate_change_scope(
            path_scope=descriptor.path_scope,
            complexity_band=descriptor.complexity_band,
            estimated_files_changed=cls._safe_int(context.get("estimated_files_changed")),
            estimated_loc_changed=cls._safe_int(context.get("estimated_loc_changed")),
        )

        if descriptor.mutation_mode == "workspace":
            policy_audit = RuntimePolicyService.evaluate_draft_policy(
                path_scope=descriptor.path_scope,
                estimated_files_changed=estimated_files_changed,
                estimated_loc_changed=estimated_loc_changed,
            )
            policy_decision = policy_audit.decision
            policy_status_code = policy_audit.status_code
            if policy_audit.decision == "deny":
                allowed_policies = []
                compiler_notes.append("runtime_policy_denied_scope")
            elif policy_audit.decision == "review":
                requires_human_approval = True
                compiler_notes.append("runtime_policy_requires_human_review")

        declared_intent = str(context.get("intent_class") or "").strip() or IntentClassificationService.default_intent_for_descriptor(
            task_semantic=descriptor.task_semantic,
            mutation_mode=descriptor.mutation_mode,
        )
        risk_score = cls._derive_risk_score(descriptor, context)
        intent_audit = IntentClassificationService.evaluate(
            intent_declared=declared_intent,
            path_scope=descriptor.path_scope,
            risk_score=risk_score,
            policy_decision=policy_decision,
            policy_status_code=policy_status_code,
        )
        if intent_audit.execution_decision == "DRAFT_REJECTED_FORBIDDEN_SCOPE":
            allowed_policies = []
            compiler_notes.append("intent_rejected_scope")
        elif intent_audit.execution_decision == "RISK_SCORE_TOO_HIGH":
            allowed_policies = []
            compiler_notes.append("intent_rejected_high_risk")
        elif intent_audit.execution_decision == "HUMAN_APPROVAL_REQUIRED":
            requires_human_approval = True
            compiler_notes.append("intent_requires_human_approval")

        provider_cfg = ProviderService.get_config()
        topology_bindings = ProviderTopologyService.bindings_for_descriptor(provider_cfg, descriptor)
        constrained_bindings = ProviderTopologyService.constrain_bindings(
            topology_bindings,
            requested_provider=context.get("requested_provider"),
            requested_model=context.get("requested_model"),
        )
        if constrained_bindings != topology_bindings:
            compiler_notes.append("binding_candidates_narrowed_by_request")

        allowed_binding_modes = cls._compile_binding_modes(
            descriptor,
            context,
            requires_human_approval=requires_human_approval,
            compiler_notes=compiler_notes,
        )

        return TaskConstraints(
            allowed_policies=allowed_policies,  # type: ignore[arg-type]
            allowed_binding_modes=allowed_binding_modes,  # type: ignore[arg-type]
            requires_human_approval=requires_human_approval,
            allowed_bindings=constrained_bindings,
            surface=surface,
            workspace_mode=workspace_mode,
            policy_decision=policy_decision,
            policy_status_code=policy_status_code,
            intent_effective=intent_audit.intent_effective,
            budget_mode=budget_mode,
            compiler_notes=compiler_notes,
        )
